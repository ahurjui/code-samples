"""Page-text cleaner — ligatures, de-hyphenation, ToC, headers.

The cleaner is stateful per-call: running-header detection needs to
see all pages of a book together to find lines that repeat. It is
also idempotent — calling `clean` on already-clean text returns it
unchanged.

docs-ref: docs/modules/core/book-rag.md#chunking-strategy
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import replace

from app.core.rag.book_ingestion.extractor import ExtractedPage

# A line is treated as a running header/footer if it appears verbatim
# on at least this fraction of pages and is in the top or bottom 3
# non-empty lines of each page.
_HEADER_REPEAT_THRESHOLD = 0.30
_HEADER_BAND = 3

# ToC line heuristic: dots run of >= 5, surrounded by non-dot text on
# both sides, ending with a number.
_TOC_PATTERN = re.compile(r"\.{5,}\s*\d+\s*$")

# De-hyphenation: a hyphen at the end of a line followed by whitespace
# and a lowercase letter — collapse and remove the hyphen + newline.
# Capitalised next token = intentional hyphen (Dixon-Coles), keep it.
_HYPHEN_BREAK_LOWER = re.compile(r"-\n(?=[a-z])")
_HYPHEN_BREAK_UPPER = re.compile(r"-\n(?=[A-Z])")


class PageCleaner:
    """Stateless object — `clean()` operates on the full page list."""

    def clean(self, pages: list[ExtractedPage]) -> list[ExtractedPage]:
        """Return a new list with normalised text on each page.

        Pipeline (in order):
            1. NFKD-normalise text on every page (folds ligatures).
            2. Detect repeated top/bottom-band lines across pages and
               remove them (running headers/footers).
            3. Drop ToC dot-leader lines page by page.
            4. De-hyphenate line-end breaks before lowercase letters.
            5. Collapse triple+ blank lines down to two.
        """
        normalised = [self._nfkd(page) for page in pages]
        headers = self._detect_running_headers(normalised)
        return [self._clean_one(page, headers) for page in normalised]

    @staticmethod
    def _nfkd(page: ExtractedPage) -> ExtractedPage:
        return replace(page, text=unicodedata.normalize("NFKD", page.text))

    @staticmethod
    def _detect_running_headers(pages: list[ExtractedPage]) -> set[str]:
        """Return the set of top/bottom-band lines that repeat too often."""
        candidates: Counter[str] = Counter()
        page_count = max(len(pages), 1)
        for page in pages:
            non_empty = [line for line in page.text.splitlines() if line.strip()]
            band = non_empty[:_HEADER_BAND] + non_empty[-_HEADER_BAND:]
            for line in set(band):
                candidates[line.strip()] += 1
        threshold = max(2, int(page_count * _HEADER_REPEAT_THRESHOLD))
        return {line for line, count in candidates.items() if count >= threshold}

    @classmethod
    def _clean_one(cls, page: ExtractedPage, headers: set[str]) -> ExtractedPage:
        text = page.text

        # Strip running headers.
        if headers:
            kept_lines = [line for line in text.splitlines() if line.strip() not in headers]
            text = "\n".join(kept_lines)

        # Drop ToC lines.
        kept_lines = [line for line in text.splitlines() if not _TOC_PATTERN.search(line)]
        text = "\n".join(kept_lines)

        # De-hyphenate before lowercase; preserve before uppercase
        # (Dixon-Coles).
        text = _HYPHEN_BREAK_LOWER.sub("", text)
        # The Dixon-\nColes case: drop only the newline so the hyphen
        # stays.
        text = _HYPHEN_BREAK_UPPER.sub("-", text)

        # Collapse 3+ blank lines.
        text = re.sub(r"\n{3,}", "\n\n", text)

        return replace(page, text=text)
