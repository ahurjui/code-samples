"""In-process BM25 index for hybrid retrieval.

Uses `rank_bm25.BM25Okapi`. The full corpus fits comfortably in
memory for the 8-book scope; if the corpus ever outgrows that, this
module is the swap-in seam (Whoosh, Tantivy).

docs-ref: docs/modules/core/book-rag.md#hybrid-retrieval-vector--bm25--rrf
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

# Tokeniser: NFKD lowercase, then `\b[a-z0-9-]{2,}\b`. Keeps hyphenated
# terms (dixon-coles, time-decay), drops punctuation and short stop-tokens.
_TOKEN_RE = re.compile(r"\b[a-z0-9-]{2,}\b")


def _tokenise(text: str) -> list[str]:
    nfkd = unicodedata.normalize("NFKD", text).lower()
    return _TOKEN_RE.findall(nfkd)


@dataclass(frozen=True, slots=True)
class Bm25Index:
    """Read-only BM25 index. Build once, save, reload at startup."""

    ids: list[str]
    tokens_per_doc: list[list[str]]

    @classmethod
    def build(cls, *, documents: list[tuple[str, str]]) -> Bm25Index:
        """Tokenise every document and return a fresh index.

        Args:
            documents: List of `(chunk_id, text)`. Order is preserved
                so identical inputs produce identical indices.
        """
        ids = [doc_id for doc_id, _ in documents]
        tokens_per_doc = [_tokenise(text) for _, text in documents]
        return cls(ids=ids, tokens_per_doc=tokens_per_doc)

    def save(self, path: Path) -> None:
        """Persist the index as JSON at `path`."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"ids": self.ids, "tokens": self.tokens_per_doc},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> Bm25Index:
        """Load a previously saved index from `path`."""
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(ids=list(data["ids"]), tokens_per_doc=list(data["tokens"]))

    def query(
        self,
        text: str,
        *,
        top_k: int,
        allowed_ids: set[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Return the top-`top_k` `(chunk_id, score)` pairs.

        Args:
            text: User query — tokenised the same way the corpus was.
            top_k: Maximum results to return.
            allowed_ids: When set, only score documents whose id is in
                this set. Used by the retriever to apply a `where`
                filter consistently across both legs.
        """
        from rank_bm25 import BM25Okapi

        if not self.ids:
            return []
        # Guard: if every document tokenised to nothing (e.g., all single-char
        # inputs that the tokeniser drops), BM25Okapi raises ZeroDivisionError
        # when computing average IDF over an empty vocabulary.
        if not any(self.tokens_per_doc):
            return []
        bm25 = BM25Okapi(self.tokens_per_doc)
        query_tokens = _tokenise(text)
        if not query_tokens:
            return []
        scores = bm25.get_scores(query_tokens)
        ranked = sorted(
            zip(self.ids, scores, strict=False),
            key=lambda pair: pair[1],
            reverse=True,
        )
        if allowed_ids is not None:
            ranked = [pair for pair in ranked if pair[0] in allowed_ids]
        return ranked[:top_k]

    def term_count(self) -> int:
        """Return the unique-term vocabulary size."""
        vocab: set[str] = set()
        for tokens in self.tokens_per_doc:
            vocab.update(tokens)
        return len(vocab)
