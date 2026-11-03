"""`BookRetriever` — vector + BM25 + Reciprocal Rank Fusion.

Returns `BookSnippet`s: structured citations ready for Strategy
specs and the chat assistant. Identical query goes to both legs;
RRF (k=60) combines them rank-wise rather than score-wise so the
two ranking spaces don't need calibration.

docs-ref: docs/modules/core/book-rag.md#hybrid-retrieval-vector--bm25--rrf
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.core.rag.book_ingestion.bm25 import Bm25Index
from app.core.rag.chroma_client import ChromaCollection
from app.core.rag.embedder import Embedder

_log = logging.getLogger(__name__)
_DEFAULT_OVERFETCH_PER_LEG = 25


@dataclass(frozen=True, slots=True)
class BookSnippet:
    """One retrieval result.

    Attributes:
        book_slug: Source book slug.
        book_title: Display title.
        chapter: Chapter title.
        page_start: First printed page.
        page_end: Last printed page.
        topic_tags: List form (csv split done at retrieval time).
        text: Chunk body.
        score: Fused RRF score (higher = better).
        chunk_id: `<slug>#NNNN`.
    """

    book_slug: str
    book_title: str
    chapter: str
    page_start: int
    page_end: int
    topic_tags: list[str]
    text: str
    score: float
    chunk_id: str


class BookRetriever:
    """Constructed once at app boot; reused across calls."""

    def __init__(
        self,
        *,
        collection: ChromaCollection,
        embedder: Embedder,
        bm25: Bm25Index,
    ) -> None:
        self._collection = collection
        self._embedder = embedder
        self._bm25 = bm25

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        where: dict[str, Any] | None = None,
        namespace_filter: list[str] | None = None,
        rrf_k: int = 60,
    ) -> list[BookSnippet]:
        """Return top-`top_k` `BookSnippet`s fused from both legs.

        Args:
            query: Free-form text query.
            top_k: Maximum number of snippets to return.
            where: Optional raw Chroma ``where`` metadata filter. Merged with
                the namespace filter when both are supplied.
            namespace_filter: When non-None, only return snippets whose chunk
                metadata ``namespace`` field is in this list. Chunks lacking
                the ``namespace`` metadata field are EXCLUDED (Chroma's ``$in``
                operator does not match missing fields). Graceful degradation:
                callers should pass ``namespace_filter=None`` for un-reingested
                corpora.
            rrf_k: Reciprocal rank fusion constant (default 60).

        Returns:
            List of BookSnippet, length <= top_k.
        """
        if not query.strip():
            return []
        overfetch = max(top_k * 5, _DEFAULT_OVERFETCH_PER_LEG)

        effective_where = _build_where(where=where, namespace_filter=namespace_filter)
        vector_hits = self._vector_search(query, where=effective_where, n_results=overfetch)
        # Restrict BM25 to the same IDs when any metadata filter is active so both
        # legs stay in sync (graceful degradation: no filter → no restriction).
        allowed_ids = {h["chunk_id"] for h in vector_hits} if effective_where is not None else None
        bm25_pairs = self._bm25.query(query, top_k=overfetch, allowed_ids=allowed_ids)

        fused = self._reciprocal_rank_fusion(
            vector_ids=[h["chunk_id"] for h in vector_hits],
            bm25_ids=[doc_id for doc_id, _ in bm25_pairs],
            rrf_k=rrf_k,
        )

        meta_by_id: dict[str, dict] = {h["chunk_id"]: h for h in vector_hits}
        missing_ids = [chunk_id for chunk_id, _ in fused if chunk_id not in meta_by_id]
        if missing_ids:
            for hit in self._lookup_by_ids(missing_ids):
                meta_by_id[hit["chunk_id"]] = hit

        snippets: list[BookSnippet] = []
        for chunk_id, score in fused[:top_k]:
            hit = meta_by_id.get(chunk_id)
            if hit is None:
                _log.warning("BookRetriever: missing metadata for %s", chunk_id)
                continue
            snippets.append(_to_snippet(hit, score=score))
        return snippets

    def _vector_search(
        self, query: str, *, where: dict[str, Any] | None, n_results: int
    ) -> list[dict[str, Any]]:
        embedding = self._embedder.embed([query])
        kwargs: dict[str, Any] = {
            "query_embeddings": embedding,
            "n_results": n_results,
        }
        if where is not None:
            kwargs["where"] = where
        result = self._collection.query(**kwargs)  # type: ignore[arg-type]
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[None] * len(ids)])[0]
        metadatas = (result.get("metadatas") or [[None] * len(ids)])[0]
        hits: list[dict[str, Any]] = []
        for chunk_id, doc, meta in zip(ids, documents, metadatas, strict=False):
            entry = dict(meta or {})
            entry["chunk_id"] = chunk_id
            entry["text"] = doc or ""
            hits.append(entry)
        return hits

    def _lookup_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        raw = self._collection.get(ids=ids)  # type: ignore[attr-defined]
        out: list[dict[str, Any]] = []
        for chunk_id, doc, meta in zip(
            raw.get("ids", []),
            raw.get("documents", []) or [None] * len(ids),
            raw.get("metadatas", []) or [None] * len(ids),
            strict=False,
        ):
            entry = dict(meta or {})
            entry["chunk_id"] = chunk_id
            entry["text"] = doc or ""
            out.append(entry)
        return out

    @staticmethod
    def _reciprocal_rank_fusion(
        *, vector_ids: list[str], bm25_ids: list[str], rrf_k: int
    ) -> list[tuple[str, float]]:
        scores: dict[str, float] = {}
        first_seen: dict[str, int] = {}
        for rank, doc_id in enumerate(vector_ids):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (rrf_k + rank + 1)
            first_seen.setdefault(doc_id, rank)
        for rank, doc_id in enumerate(bm25_ids):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (rrf_k + rank + 1)
            first_seen.setdefault(doc_id, len(vector_ids) + rank)
        return sorted(
            scores.items(),
            key=lambda item: (-item[1], first_seen[item[0]]),
        )


def _build_where(
    *,
    where: dict[str, Any] | None,
    namespace_filter: list[str] | None,
) -> dict[str, Any] | None:
    """Merge an optional caller ``where`` clause with a namespace filter.

    Namespace filter semantics: only chunks whose ``namespace`` metadata field
    is in ``namespace_filter`` are kept. Chunks that lack the ``namespace``
    field are excluded (Chroma does not support ``$exists``); they will be
    included automatically once the corpus is reingested with namespace tags.
    This is the documented graceful-degradation behaviour for v1: the filter
    is a no-op when ``namespace_filter`` is ``None`` or empty, so callers on
    un-reingested corpora can simply omit the argument.

    Args:
        where: Optional existing Chroma metadata filter from the caller.
        namespace_filter: Optional list of namespace strings to restrict to.

    Returns:
        A single merged Chroma ``where`` dict, or None when neither filter
        is active.
    """
    if not namespace_filter:
        return where  # no namespace restriction; pass through as-is

    # Filter to chunks whose namespace is in the allow-list.
    ns_clause: dict[str, Any] = {"namespace": {"$in": namespace_filter}}

    if where is None:
        return ns_clause

    # Both filters active: wrap in $and.
    return {"$and": [where, ns_clause]}


def _to_snippet(hit: dict[str, Any], *, score: float) -> BookSnippet:
    raw_tags = hit.get("topic_tags", "") or ""
    tags = [t for t in raw_tags.split(",") if t]
    return BookSnippet(
        book_slug=str(hit.get("book_slug", "")),
        book_title=str(hit.get("book_title", "")),
        chapter=str(hit.get("chapter", "")),
        page_start=int(hit.get("page_start", 0)),
        page_end=int(hit.get("page_end", 0)),
        topic_tags=tags,
        text=str(hit.get("text", "")),
        score=score,
        chunk_id=str(hit["chunk_id"]),
    )
