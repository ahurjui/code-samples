"""Stage 3 — per-(market, selection) book-snippet retrieval.

12 fixed query templates, top_k=1 per template, namespace-filtered via
config/rag/book_namespaces.yaml. Session-scoped cache with composite key
(strategy_version, corpus_hash, template_hash) so cache invalidates
correctly on corpus reingest, prompt edits, or template changes.

docs-ref: docs/superpowers/specs/2026-05-10-issue-399-llm-book-grounded-redesign-design.md#per-market-selection-snippet-retrieval
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Protocol

from app.core.rag.factories import load_book_namespaces

_log = logging.getLogger(__name__)


# docs-ref: docs/superpowers/specs/2026-05-10-issue-399-llm-book-grounded-redesign-design.md#per-market-selection-snippet-retrieval
QUERY_TEMPLATES: dict[tuple[str, str], str] = {
    ("match_winner_1x2", "home"): "home advantage superiority form dominance match outcome",
    ("match_winner_1x2", "draw"): "draw probability low scoring equilibrium variance suppression",
    ("match_winner_1x2", "away"): "away upset counterattacking efficiency road performance",
    ("over_under_2_5", "over"): "high expected goals attacking tempo open football Poisson",
    ("over_under_2_5", "under"): "low scoring defensive compactness variance suppression",
    ("btts", "yes"): "mutual scoring offensive balance defensive instability correlation",
    ("btts", "no"): "clean sheet scoring suppression asymmetric attack",
    ("asian_handicap_0", "home"): "draw no bet home edge balanced match pricing",
    ("asian_handicap_0", "away"): "draw no bet away value balanced market inefficiency",
    ("double_chance", "1X"): "home protection draw coverage asymmetric safety",
    ("double_chance", "X2"): "away protection underdog resilience draw coverage",
    ("double_chance", "12"): "draw avoidance high variance decisive outcome",
}


# docs-ref: docs/superpowers/specs/2026-05-10-issue-399-llm-book-grounded-redesign-design.md#per-market-selection-snippet-retrieval
def compute_template_hash(templates: dict[tuple[str, str], str]) -> str:
    """SHA256 hex over the canonical JSON serialisation of the templates dict.

    Used as part of the composite cache key in SnippetCache so the cache
    invalidates on any template edit (e.g. a query phrase change in v2.1).

    Args:
        templates: Per-(market, selection) query template dict.

    Returns:
        64-character SHA256 hex string.
    """
    serial = json.dumps(
        sorted([(list(k), v) for k, v in templates.items()]),
        sort_keys=True,
    )
    return hashlib.sha256(serial.encode()).hexdigest()


class _BookRetrieverProtocol(Protocol):
    """Structural type of `BookRetriever.retrieve` for the cache.

    Captures only the call shape SnippetCache needs; concrete implementations
    (notably `BookRetriever`) match this signature already.
    """

    def retrieve(
        self,
        query: str,
        *,
        top_k: int,
        namespace_filter: list[str] | None = None,
    ) -> list[Any]: ...


# docs-ref: docs/superpowers/specs/2026-05-10-issue-399-llm-book-grounded-redesign-design.md#per-market-selection-snippet-retrieval
class SnippetCache:
    """Memoises the 12 retrievals across all fixtures within a strategy session.

    Cache invalidates on any of:
    - strategy_version bump (prompt edit elsewhere)
    - corpus reingest (corpus_hash changes)
    - template hash change (template_dict edit)
    """

    def __init__(self) -> None:
        """Initialise with empty cache state."""
        self._data: dict[tuple[str, str], list[Any]] | None = None
        self._key: tuple[str, str, str] | None = None

    def get(
        self,
        retriever: _BookRetrieverProtocol,
        *,
        strategy_version: str,
        corpus_hash: str,
    ) -> dict[tuple[str, str], list[Any]]:
        """Return cached or freshly-computed per-(market, selection) snippets.

        Args:
            retriever: BookRetriever-shaped object with `.retrieve(query, *,
                top_k, namespace_filter)` method.
            strategy_version: Current strategy version string (e.g. "2.0.0").
            corpus_hash: Hash of the current corpus state (caller computes).

        Returns:
            Dict mapping (market, selection) → list[BookSnippet] (top_k=1 per).
            Failed retrievals yield an empty list rather than propagating.
        """
        current_key = (
            strategy_version,
            corpus_hash,
            compute_template_hash(QUERY_TEMPLATES),
        )
        if self._key != current_key or self._data is None:
            ns_cfg = load_book_namespaces().get("namespace_per_query", {})
            data: dict[tuple[str, str], list[Any]] = {}
            for key, query in QUERY_TEMPLATES.items():
                # T8 changed YAML keys to "market|selection" strings.
                yaml_key = f"{key[0]}|{key[1]}"
                ns_filter = ns_cfg.get(yaml_key) or None
                try:
                    data[key] = retriever.retrieve(
                        query,
                        top_k=1,
                        namespace_filter=ns_filter,
                    )
                except (RuntimeError, OSError, ValueError):
                    _log.warning("retrieval failed for key=%s", key, exc_info=True)
                    data[key] = []
            self._data = data
            self._key = current_key
        return self._data
