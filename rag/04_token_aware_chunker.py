"""Token-based, paragraph-aware chunker for book pages.

Each chunk belongs to exactly one chapter — chunks at chapter
boundaries are split at the chapter edge, not by paragraph alone.

docs-ref: docs/modules/core/book-rag.md#chunking-strategy
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from app.core.rag.book_ingestion.extractor import ExtractedPage
from app.core.rag.book_ingestion.manifest import BookManifest, ChapterManifest

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")


@dataclass(frozen=True, slots=True)
class BookChunk:
    """One chunk ready for embedding + Chroma upsert.

    Attributes:
        book_slug: Source-book slug.
        book_title: Display title.
        chapter: Chapter title from the manifest.
        page_start: First printed page contributing to the chunk.
        page_end: Last printed page contributing to the chunk.
        topic_tags: Deduped union of book-level + chapter-level tags.
        text: Chunk body text (paragraphs joined by `\\n\\n`).
        char_count: `len(text)`.
        token_count: tiktoken `cl100k_base` count of `text`.
        chunk_index: Zero-based index inside the book.
    """

    book_slug: str
    book_title: str
    chapter: str
    page_start: int
    page_end: int
    topic_tags: list[str]
    text: str
    char_count: int
    token_count: int
    chunk_index: int


class BookChunker:
    """Token-bucket chunker. One book per `chunk()` call."""

    def __init__(self, *, target_tokens: int, overlap_tokens: int) -> None:
        if overlap_tokens >= target_tokens:
            raise ValueError("overlap_tokens must be < target_tokens")
        self._target = target_tokens
        self._overlap = overlap_tokens
        self._encoding = None  # lazy-loaded tiktoken encoding

    def chunk(
        self,
        pages: list[ExtractedPage],
        manifest: BookManifest,
    ) -> Iterator[BookChunk]:
        """Yield `BookChunk`s for the given pages, partitioned by chapter."""
        # Group pages by chapter (printed-page-coordinate lookup).
        per_chapter: list[tuple[ChapterManifest, list[_PageInChapter]]] = []
        chapter_index: dict[str, list[_PageInChapter]] = {ch.title: [] for ch in manifest.chapters}
        for page in pages:
            printed_page = page.pdf_page_index + 1 - manifest.page_offset
            chapter = self._lookup_chapter(printed_page, manifest.chapters)
            if chapter is None:
                continue  # front matter, back matter, or gap → skipped
            chapter_index[chapter.title].append(
                _PageInChapter(printed_page=printed_page, text=page.text)
            )
        for chapter in manifest.chapters:
            per_chapter.append((chapter, chapter_index[chapter.title]))

        # Walk chapters in document order and emit chunks. `chunk_index`
        # is global across the book.
        chunk_index = 0
        for chapter, chapter_pages in per_chapter:
            for chunk in self._chunks_for_chapter(
                manifest=manifest,
                chapter=chapter,
                pages=chapter_pages,
                chunk_index_start=chunk_index,
            ):
                yield chunk
                chunk_index += 1

    @staticmethod
    def _lookup_chapter(
        printed_page: int, chapters: list[ChapterManifest]
    ) -> ChapterManifest | None:
        for chapter in chapters:
            if chapter.page_start <= printed_page <= chapter.page_end:
                return chapter
        return None

    def _chunks_for_chapter(
        self,
        *,
        manifest: BookManifest,
        chapter: ChapterManifest,
        pages: list[_PageInChapter],
        chunk_index_start: int,
    ) -> Iterator[BookChunk]:
        if not pages:
            return
        topic_tags = list(dict.fromkeys(manifest.topic_tags + chapter.topic_tags))
        paragraphs = list(self._iter_paragraphs(pages))
        if not paragraphs:
            return

        encoding = self._get_encoding()
        chunk_index = chunk_index_start
        bucket: list[_Paragraph] = []
        bucket_tokens = 0
        for paragraph in paragraphs:
            paragraph_tokens = len(encoding.encode(paragraph.text))
            if bucket and bucket_tokens + paragraph_tokens > self._target:
                yield self._emit(
                    manifest=manifest,
                    chapter=chapter,
                    bucket=bucket,
                    chunk_index=chunk_index,
                    topic_tags=topic_tags,
                )
                chunk_index += 1
                bucket = self._carry_overlap(bucket, encoding)
                bucket_tokens = sum(len(encoding.encode(p.text)) for p in bucket)
            bucket.append(paragraph)
            bucket_tokens += paragraph_tokens
        if bucket:
            yield self._emit(
                manifest=manifest,
                chapter=chapter,
                bucket=bucket,
                chunk_index=chunk_index,
                topic_tags=topic_tags,
            )

    def _iter_paragraphs(self, pages: list[_PageInChapter]) -> Iterator[_Paragraph]:
        for page in pages:
            for raw in _PARAGRAPH_SPLIT.split(page.text):
                stripped = raw.strip()
                if stripped:
                    yield _Paragraph(
                        text=stripped,
                        page_start=page.printed_page,
                        page_end=page.printed_page,
                    )

    def _carry_overlap(self, prior: list[_Paragraph], encoding: Any) -> list[_Paragraph]:
        if not prior or self._overlap == 0:
            return []
        carry: list[_Paragraph] = []
        running = 0
        for paragraph in reversed(prior):
            tokens = len(encoding.encode(paragraph.text))
            if running + tokens > self._overlap:
                break
            carry.append(paragraph)
            running += tokens
        carry.reverse()
        return carry

    def _emit(
        self,
        *,
        manifest: BookManifest,
        chapter: ChapterManifest,
        bucket: list[_Paragraph],
        chunk_index: int,
        topic_tags: list[str],
    ) -> BookChunk:
        text = "\n\n".join(p.text for p in bucket)
        encoding = self._get_encoding()
        return BookChunk(
            book_slug=manifest.slug,
            book_title=manifest.title,
            chapter=chapter.title,
            page_start=min(p.page_start for p in bucket),
            page_end=max(p.page_end for p in bucket),
            topic_tags=topic_tags,
            text=text,
            char_count=len(text),
            token_count=len(encoding.encode(text)),
            chunk_index=chunk_index,
        )

    def _get_encoding(self) -> Any:
        if self._encoding is None:
            import tiktoken

            self._encoding = tiktoken.get_encoding("cl100k_base")
        return self._encoding


@dataclass(frozen=True, slots=True)
class _PageInChapter:
    printed_page: int
    text: str


@dataclass(frozen=True, slots=True)
class _Paragraph:
    text: str
    page_start: int
    page_end: int
