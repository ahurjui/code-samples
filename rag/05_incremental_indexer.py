"""`DocsIndexer` — walks `docs/**/*.md`, chunks, embeds, upserts.

Invoked from the CLI (`python -m app.rag.index`) and from the
scheduler (boot + nightly). Idempotent: chunk ids are derived
from `(doc_path, chunk_index)` so a re-run replaces rather than
duplicates. Orphaned ids (chunks that disappeared from the
source) are swept after each full run.

docs-ref: docs/modules/core/rag.md#docsindexer
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from pathlib import Path

from app.core.rag.chroma_client import ChromaCollection
from app.core.rag.chunker import Chunk, chunk_code, chunk_markdown
from app.core.rag.config import RagConfig
from app.core.rag.embedder import Embedder
from app.core.rag.pdf_text import extract_pdf_text

_log = logging.getLogger(__name__)

_FRONTMATTER_PATTERN = re.compile(r"^---\n.*?\n---\n", flags=re.DOTALL)


def _chunk_file(
    *,
    doc_path: Path,
    raw: str,
    chunker: str,
    max_chars: int,
    overlap_chars: int,
) -> list[Chunk]:
    """Dispatch to the appropriate chunker based on `chunker` and file extension.

    Args:
        doc_path: Source file path (used for extension detection).
        raw: Raw file content (bytes decoded to str).
        chunker: One of "markdown", "code", "mixed".
        max_chars: Char limit for markdown chunker.
        overlap_chars: Overlap chars for markdown chunker.

    Returns:
        List of `Chunk` instances; empty if the file should be skipped.
    """
    suffix = doc_path.suffix.lower()

    if chunker == "code":
        max_lines = max(1, max_chars // 80)
        overlap_lines = max(1, overlap_chars // 80)
        return chunk_code(raw, max_lines=max_lines, overlap_lines=overlap_lines)

    if chunker == "mixed":
        if suffix == ".pdf":
            try:
                pdf_text = extract_pdf_text(doc_path)
            except Exception as error:  # noqa: BLE001
                _log.warning("rag.reindex: skipping PDF %s (%s)", doc_path, error)
                return []
            max_lines = max(1, max_chars // 80)
            overlap_lines = max(1, overlap_chars // 80)
            return chunk_code(pdf_text, max_lines=max_lines, overlap_lines=overlap_lines)
        # For .md (and any other text extension) fall through to markdown.
        body = _FRONTMATTER_PATTERN.sub("", raw, count=1)
        return chunk_markdown(body, max_chars=max_chars, overlap_chars=overlap_chars)

    # Default: markdown
    body = _FRONTMATTER_PATTERN.sub("", raw, count=1)
    return chunk_markdown(body, max_chars=max_chars, overlap_chars=overlap_chars)


class DocsIndexer:
    """Walks the configured doc globs and refreshes one Chroma collection.

    The indexer is stateless with respect to callers — every
    `reindex()` call rescans the filesystem and diffs against the
    current collection contents. Runs take O(docs * chunks_per_doc)
    time; at the current doc corpus size that's under a minute even
    on a laptop.
    """

    def __init__(
        self,
        *,
        config: RagConfig,
        repo_root: Path,
        collection: ChromaCollection,
        embedder: Embedder,
    ) -> None:
        """Bind the indexer to a collection + embedder.

        Args:
            config: Validated `RagConfig`.
            repo_root: The repo root directory (glob roots resolve
                against this). The module doesn't guess it — callers
                pass it explicitly so tests can point at a tmpdir.
            collection: Target `ChromaCollection`.
            embedder: `Embedder` implementation.
        """
        self._config = config
        self._repo_root = repo_root
        self._collection = collection
        self._embedder = embedder

    def reindex(self, *, collection_name: str = "docs") -> int:
        """Run one full reindex cycle; return the number of chunks upserted.

        Steps:
            1. Enumerate candidate docs from
               `config.collections[collection_name].source_globs`,
               minus the excludes.
            2. For each doc, strip front-matter and chunk it.
            3. Embed + upsert chunks in batches.
            4. Sweep orphaned ids (present in Chroma, absent on disk).
        """
        settings = self._config.collections[collection_name]
        docs = list(self._enumerate_docs(settings.source_globs, settings.excludes))
        _log.info("rag.reindex: %s — scanning %d files", collection_name, len(docs))

        all_ids: list[str] = []
        pending_batch: list[tuple[str, Chunk, str]] = []
        total_upserted = 0

        for doc_path in docs:
            # For mixed chunker + PDF, skip read_text — _chunk_file calls extract_pdf_text directly.
            if settings.chunker == "mixed" and doc_path.suffix.lower() == ".pdf":
                raw = ""
            else:
                try:
                    raw = doc_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as error:
                    _log.warning("rag.reindex: skipping %s (%s)", doc_path, error)
                    continue
            relative = doc_path.relative_to(self._repo_root).as_posix()
            chunks = _chunk_file(
                doc_path=doc_path,
                raw=raw,
                chunker=settings.chunker,
                max_chars=self._config.chunk.max_chars,
                overlap_chars=self._config.chunk.overlap_chars,
            )
            for index, chunk in enumerate(chunks):
                chunk_id = f"{relative}#{index}"
                all_ids.append(chunk_id)
                pending_batch.append((chunk_id, chunk, relative))
                if len(pending_batch) >= self._config.batch_size:
                    total_upserted += self._flush_batch(pending_batch)
                    pending_batch = []

        if pending_batch:
            total_upserted += self._flush_batch(pending_batch)

        self._sweep_orphans(all_ids)
        _log.info(
            "rag.reindex: %s — upserted %d chunks across %d docs",
            collection_name,
            total_upserted,
            len(docs),
        )
        return total_upserted

    def _enumerate_docs(
        self, source_globs: Iterable[str], excludes: Iterable[str]
    ) -> Iterable[Path]:
        """Resolve globs + excludes against `repo_root`; yield `Path`s."""
        exclude_patterns = list(excludes)
        seen: set[Path] = set()
        for pattern in source_globs:
            for candidate in self._repo_root.glob(pattern):
                if not candidate.is_file():
                    continue
                relative = candidate.relative_to(self._repo_root).as_posix()
                if any(_matches_glob(relative, pattern) for pattern in exclude_patterns):
                    continue
                if candidate in seen:
                    continue
                seen.add(candidate)
                yield candidate

    def _flush_batch(self, batch: list[tuple[str, Chunk, str]]) -> int:
        """Embed + upsert a batch. Returns the count of upserted ids."""
        ids = [row[0] for row in batch]
        texts_for_embedding = [_compose_embedding_text(row[1]) for row in batch]
        documents = [row[1].text for row in batch]
        metadatas = []
        for row in batch:
            meta: dict = {
                "source": row[2],
                "heading_path": row[1].heading_path,
            }
            # Code chunks encode line range in heading_path as "L{start}-L{end}".
            # Promote to dedicated metadata keys for downstream retrieval.
            if row[1].heading_path.startswith("L") and "-L" in row[1].heading_path:
                try:
                    parts = row[1].heading_path.lstrip("L").split("-L")
                    meta["line_start"] = int(parts[0])
                    meta["line_end"] = int(parts[1])
                except (ValueError, IndexError):
                    pass
            metadatas.append(meta)
        embeddings = self._embedder.embed(texts_for_embedding)
        self._collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        return len(ids)

    def _sweep_orphans(self, live_ids: list[str]) -> None:
        """Remove chunk ids present in Chroma but absent from disk.

        A chunk becomes orphaned when a doc is renamed, deleted, or
        restructured such that its chunk count shrinks. Without the
        sweep, stale snippets would surface in retrieval forever.
        """
        existing = _ids_in_collection(self._collection)
        live_set = set(live_ids)
        orphans = [chunk_id for chunk_id in existing if chunk_id not in live_set]
        if orphans:
            self._collection.delete(ids=orphans)
            _log.info("rag.reindex: swept %d orphan chunk ids", len(orphans))


def _matches_glob(relative: str, pattern: str) -> bool:
    """Return True if `relative` matches the shell-style glob `pattern`."""
    from fnmatch import fnmatchcase

    return fnmatchcase(relative, pattern)


def _compose_embedding_text(chunk: Chunk) -> str:
    """Prepend the heading path so the embedder sees the doc context.

    Boosts retrieval quality: a snippet about "admin endpoints
    reject non-admin with 403" embedded alone can collide with
    unrelated "403" references; prepending "Admin console > Rules >
    …" gives the vector a stable topical anchor.
    """
    if not chunk.heading_path:
        return chunk.text
    return f"{chunk.heading_path}\n\n{chunk.text}"


def _ids_in_collection(collection: ChromaCollection) -> list[str]:
    """Return every id currently stored in the collection.

    Chroma exposes `get()` with no filter for full-scan retrieval.
    The `ChromaCollection` protocol in `chroma_client` intentionally
    omits this method because only the indexer needs it — we reach
    through the wrapper here.
    """
    # Chroma's real API: `collection.get()` returns `{"ids": [...]}`.
    raw = collection.get()  # type: ignore[attr-defined]
    return list(raw.get("ids", []))
