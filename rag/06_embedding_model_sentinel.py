"""Shared embedding-model sentinel helpers for RAG indexers.

Every Chroma corpus indexer writes a single sentinel chunk recording the
embedding model used to produce its vectors.  At scheduler boot,
``ensure_*_indexed`` reads this sentinel and forces a reindex if the
configured model has changed (vectors from different models are
incompatible).  The audit (``scripts/docs-audit.mjs``) reads the same
sentinel to assert every corpus is indexed under the configured model.

This module is the single source of truth for that protocol.  Five
indexers used to keep their own copies of ``_write_model_sentinel`` and
``_MODEL_SENTINEL_ID``; one custom indexer (``tickets_indexer``) skipped
the copy and broke the audit (#373).  Centralising the helpers here
prevents the same trap for any future custom indexer.

Usage:

    from app.core.rag.sentinel import (
        MODEL_SENTINEL_ID, read_indexed_model, write_model_sentinel,
    )

    # After upserting real chunks:
    write_model_sentinel(collection, model_name, embedding_dimension)

    # Before deciding whether to reindex:
    indexed = read_indexed_model(collection)
    if indexed != configured_model:
        ...  # reindex

docs-ref: docs/modules/core/rag.md#scheduler-job-ragindexdocs
"""

from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

# Sentinel chunk stored in every RAG collection to track which embedding
# model produced the current index.  The ``__meta__/`` prefix keeps it
# visually distinguishable from real chunk ids (e.g. ``path/to/doc.md#N``)
# and prevents accidental collisions with content keys.
MODEL_SENTINEL_ID = "__meta__/embedding_model"


_DEFAULT_METADATA: dict = {"source": "__meta__", "heading_path": ""}


def write_model_sentinel(
    collection: object,
    model: str,
    dimension: int,
    *,
    metadata: dict | None = None,
) -> None:
    """Upsert the model sentinel chunk into ``collection``.

    Uses a zero-vector embedding so the sentinel never surfaces in
    similarity queries (cosine distance to any real vector is 1.0,
    the worst possible match).

    Logs and swallows any error — failing to write the sentinel is a
    visibility issue, not a correctness issue, and must not abort the
    indexer's main work.

    Args:
        collection: The Chroma collection to write into.  Real Chroma
            client (not the read-only ``ChromaCollection`` protocol).
        model: The embedding-model name to record (e.g.
            ``sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2``).
        dimension: Embedding dimension; the zero-vector must match the
            collection's HNSW space dimension.
        metadata: Optional metadata dict for the sentinel row.  Defaults
            to the docs/code/specs/kb/tickets shape
            ``{"source": "__meta__", "heading_path": ""}``.  The books
            corpus passes its own schema-specific shape.
    """
    md = metadata if metadata is not None else _DEFAULT_METADATA
    try:
        collection.upsert(  # type: ignore[attr-defined]
            ids=[MODEL_SENTINEL_ID],
            embeddings=[[0.0] * dimension],
            metadatas=[md],
            documents=[model],
        )
    except Exception as error:  # noqa: BLE001 — sentinel write is best-effort
        _log.warning("rag: could not write model sentinel: %s", error)


def read_indexed_model(collection: object) -> str | None:
    """Return the model name recorded in ``collection``'s sentinel, or None.

    Returns ``None`` when the sentinel is absent (corpus has never been
    indexed, or was indexed by a pre-sentinel build) or when the
    underlying ``get`` call fails for any reason — callers must treat
    ``None`` as "unknown" and decide whether to force a reindex.

    Args:
        collection: The Chroma collection to read from.

    Returns:
        The stored model name string, or ``None`` if the sentinel is
        absent or the read call fails.
    """
    try:
        result = collection.get(ids=[MODEL_SENTINEL_ID])  # type: ignore[attr-defined]
        docs = result.get("documents", [])
        return docs[0] if docs else None
    except Exception:  # noqa: BLE001 — caller treats None as "unknown"
        return None
