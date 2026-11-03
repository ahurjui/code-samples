"""Tests for `BookRetriever`.

# spec-ref: docs/modules/core/book-rag.md#hybrid-retrieval-vector--bm25--rrf
"""

from __future__ import annotations

from app.core.rag.book_ingestion.bm25 import Bm25Index
from app.core.rag.book_retriever import BookRetriever, BookSnippet


class _FakeEmbedder:
    def embed(self, texts):  # type: ignore[no-untyped-def]
        return [[1.0, 0.0, 0.0]] * len(list(texts))


class _FakeCollection:
    """Stub Chroma collection that returns canned vector results."""

    def __init__(self, *, vector_results: list[tuple[str, dict]]):
        self._vector_results = vector_results

    def query(self, query_embeddings, n_results, where=None):
        ids = [doc_id for doc_id, _ in self._vector_results]
        metadatas = [meta for _, meta in self._vector_results]
        if where is not None:
            keep = [
                (i, m)
                for i, m in zip(ids, metadatas, strict=False)
                if all(m.get(k) == v for k, v in where.items())
            ]
            ids = [i for i, _ in keep]
            metadatas = [m for _, m in keep]
        return {
            "ids": [ids[:n_results]],
            "documents": [["doc-" + i for i in ids[:n_results]]],
            "metadatas": [metadatas[:n_results]],
            "distances": [[0.1 * (rank + 1) for rank in range(min(n_results, len(ids)))]],
        }

    def get(self, ids):
        return {"ids": [], "documents": [], "metadatas": []}


def _meta(book_slug: str = "soccermatics") -> dict:
    return {
        "book_slug": book_slug,
        "book_title": "Soccermatics",
        "chapter": "Poisson Predictions",
        "page_start": 46,
        "page_end": 50,
        "topic_tags": "poisson,dixon-coles",
        "chunk_index": 142,
    }


def test_returns_book_snippets() -> None:
    bm25 = Bm25Index.build(
        documents=[
            ("a#0001", "dixon coles correction"),
            ("a#0002", "kelly criterion"),
        ]
    )
    collection = _FakeCollection(
        vector_results=[
            ("a#0001", _meta()),
            ("a#0002", _meta()),
        ]
    )
    retriever = BookRetriever(
        collection=collection,
        embedder=_FakeEmbedder(),
        bm25=bm25,
    )
    results = retriever.retrieve("dixon coles", top_k=2)
    assert all(isinstance(r, BookSnippet) for r in results)
    assert results[0].chunk_id == "a#0001"
    assert results[0].topic_tags == ["poisson", "dixon-coles"]


def test_rrf_fuses_two_legs() -> None:
    bm25 = Bm25Index.build(
        documents=[
            ("a#0001", "alpha beta"),
            ("a#0002", "gamma alpha"),
        ]
    )
    collection = _FakeCollection(
        vector_results=[
            ("a#0001", _meta()),
            ("a#0002", _meta()),
        ]
    )
    retriever = BookRetriever(
        collection=collection,
        embedder=_FakeEmbedder(),
        bm25=bm25,
    )
    results = retriever.retrieve("alpha", top_k=2)
    assert {r.chunk_id for r in results} == {"a#0001", "a#0002"}


def test_where_filter_constrains_bm25_to_vector_filtered_ids() -> None:
    bm25 = Bm25Index.build(
        documents=[
            ("a#0001", "kelly"),
            ("b#0001", "kelly"),
        ]
    )

    class _CollectionWithFilter:
        def __init__(self) -> None:
            self.last_where: dict | None = None

        def query(self, query_embeddings, n_results, where=None):
            self.last_where = where
            all_hits = [
                ("a#0001", _meta(book_slug="logic-of-sports-betting")),
                ("b#0001", _meta(book_slug="football-hackers")),
            ]
            if where:
                all_hits = [
                    (i, m) for i, m in all_hits if all(m.get(k) == v for k, v in where.items())
                ]
            ids = [i for i, _ in all_hits[:n_results]]
            metadatas = [m for _, m in all_hits[:n_results]]
            return {
                "ids": [ids],
                "documents": [["doc-" + i for i in ids]],
                "metadatas": [metadatas],
                "distances": [[0.1] * len(ids)],
            }

        def get(self, ids):
            return {"ids": [], "documents": [], "metadatas": []}

    collection = _CollectionWithFilter()
    retriever = BookRetriever(
        collection=collection,
        embedder=_FakeEmbedder(),
        bm25=bm25,
    )
    results = retriever.retrieve(
        "kelly",
        top_k=10,
        where={"book_slug": "logic-of-sports-betting"},
    )
    assert collection.last_where == {"book_slug": "logic-of-sports-betting"}
    assert {r.chunk_id for r in results} == {"a#0001"}


def test_top_k_honoured() -> None:
    bm25 = Bm25Index.build(documents=[("a#0001", "x"), ("a#0002", "x"), ("a#0003", "x")])
    collection = _FakeCollection(
        vector_results=[("a#0001", _meta()), ("a#0002", _meta()), ("a#0003", _meta())]
    )
    retriever = BookRetriever(
        collection=collection,
        embedder=_FakeEmbedder(),
        bm25=bm25,
    )
    results = retriever.retrieve("x", top_k=2)
    assert len(results) == 2
