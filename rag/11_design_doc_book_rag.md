---
last_verified: 2026-05-12
---

# Book RAG Ingestion

<!-- code-ref: backend/app/core/rag/book_ingestion/manifest.py#BookManifest -->
<!-- code-ref: backend/app/core/rag/book_ingestion/extractor.py#PdfExtractor -->
<!-- code-ref: backend/app/core/rag/book_ingestion/cleaner.py#PageCleaner -->
<!-- code-ref: backend/app/core/rag/book_ingestion/chunker.py#BookChunker -->
<!-- code-ref: backend/app/core/rag/book_ingestion/bm25.py#Bm25Index -->
<!-- code-ref: backend/app/core/rag/book_indexer.py#BooksIndexer -->
<!-- code-ref: backend/app/core/rag/book_retriever.py#BookRetriever -->
<!-- code-ref: backend/app/core/rag/tasks/index_books.py#ensure_books_indexed -->
<!-- code-ref: backend/app/rag/index_books.py -->

## Summary

Ingests the 8 betting/statistics books from `config/books/*.yaml` manifests into
a `portal_books` Chroma collection. At query time, `BookRetriever` fuses
vector similarity and BM25 keyword search via Reciprocal Rank Fusion (RRF)
and returns `BookSnippet` objects with full citation metadata (book, chapter,
page range). Addresses weakness W7 in the prediction system audit.

---

## Flow

1. **Boot guard** — `ensure_books_indexed()` runs on scheduler startup after
   `ensure_docs_indexed()`. It checks whether the `portal_books` Chroma
   collection is non-empty and whether the embedding model sentinel matches
   the configured model. If either check fails, `BooksIndexer.reindex()` runs.
2. **Manifest loading** — `load_manifests("config/books/*.yaml")` validates all
   YAML files against `BookManifest` / `ChapterManifest` Pydantic models.
   Missing or invalid manifests fail loudly at startup.
3. **Per-book ingestion** — for each `BookManifest`, `BooksIndexer` opens the
   source PDF and iterates over chapters.
4. **Page extraction** — `PdfExtractor.extract_chapter()` calls
   `fitz.Page.get_text()` for each page in the chapter's `[page_start, page_end]`
   range (converted from printed page to PDF index via `page_offset`). If
   `needs_ocr: true` and every page yields < 50 chars, `OcrRequiredError` is
   raised with the exact `ocrmypdf` command to run.
5. **Page cleaning** — `PageCleaner.clean()` normalises each page: maps PDF
   ligatures to ASCII (`ﬁ` → `fi`), de-hyphenates line breaks (only before
   lowercase), strips running headers/footers detected on ≥ 30% of pages, and
   drops ToC dot-leader lines.
6. **Chunk production** — `BookChunker.chunk()` splits cleaned chapter text into
   token-bounded chunks (~600 tokens, ~50-token overlap) using `tiktoken`.
   Paragraphs are never split mid-paragraph (oversized paragraphs are emitted
   whole rather than truncated).
7. **Embedding + upsert** — each chunk is embedded via `FastEmbedEmbedder`
   (same model as `portal_docs`) and upserted into Chroma with full metadata.
8. **BM25 sidecar** — after all books are indexed, `Bm25Index` rebuilds from
   all chunk texts and serialises to `/chroma/books_bm25.json`.
9. **Orphan sweep** — chunk IDs no longer present in the current manifests are
   deleted from Chroma.

---

## Architecture conventions

- Book RAG infrastructure lives in `backend/app/core/rag/`, not in any
  `modules/` subtree, because multiple consumers call `BookRetriever`
  (all Prediction System v2 strategies, the chat assistant, admin UI).
- `BooksIndexer` and `BookRetriever` are dependency-injected (no global state).
  They mirror the constructor style of `DocsIndexer` and `TicketsIndexer`.
- The embedding model is the same as `portal_docs` and `portal_tickets`
  (`paraphrase-multilingual-MiniLM-L12-v2`, 384-dim). Cross-collection
  homogeneity keeps the RAG stack simple.
- The BM25 index is an in-process `rank_bm25.BM25Okapi` instance, serialised
  as JSON next to the Chroma data volume. It is rebuilt on every full reindex.
- Manifests are the single source of truth for chapter boundaries and topic
  tags. Auto-detection from PDF font sizes was rejected as too fragile.
- Fixed Odds Sports Betting (`needs_ocr: true`) is skipped (raises
  `OcrRequiredError`) until the user runs `ocrmypdf` once on the host.

---

## Per-book YAML manifest

<!-- code-ref: backend/app/core/rag/book_ingestion/manifest.py#BookManifest -->

Each book has a YAML file under `config/books/<slug>.yaml`. Fields:

| Field | Type | Description |
|-------|------|-------------|
| `slug` | `str` | Kebab-case identifier; load-bearing (chunk IDs prefix with it) |
| `title` | `str` | Full book title for citations |
| `authors` | `list[str]` | Author list |
| `source_pdf` | `str` | Exact filename inside `PORTAL_BOOKS_DIR` |
| `topic_tags` | `list[str]` | Book-level tags merged with chapter tags on each chunk |
| `needs_ocr` | `bool` | Raise `OcrRequiredError` instead of extracting if `true` |
| `page_offset` | `int` | Reconciles printed page ↔ PDF index: `printed = pdf_index + 1 - page_offset` |

Under `chapters:` — a list of `ChapterManifest` objects:

| Field | Type | Constraints |
|-------|------|-------------|
| `title` | `str` | Non-empty |
| `page_start` | `int` | ≥ 1; printed page number |
| `page_end` | `int` | ≥ `page_start` |
| `topic_tags` | `list[str]` | Chapter-level tags (merged with book tags) |

Validation: `page_end < page_start` → `ValueError`. Overlapping chapter
ranges within the same book → `ValueError`. Empty manifest list is valid
but results in no indexing for that book.

`load_manifests(pattern)` reads all matching YAML files, validates each,
and returns a list sorted by `slug` for deterministic ordering.

---

## Chunking strategy

<!-- code-ref: backend/app/core/rag/book_ingestion/extractor.py#PdfExtractor -->
<!-- code-ref: backend/app/core/rag/book_ingestion/cleaner.py#PageCleaner -->
<!-- code-ref: backend/app/core/rag/book_ingestion/chunker.py#BookChunker -->

1. **Per-page extraction** with `fitz.Page.get_text("text")` preserving page
   order. OCR fallback: if `needs_ocr: true` and all pages return < 50 chars,
   raise `OcrRequiredError` with the exact `ocrmypdf` command.
2. **Page cleaning** via `PageCleaner`:
   - NFKD-normalise to map ligatures to ASCII (`ﬁ` → `fi`, `ﬂ` → `fl`).
   - De-hyphenate line breaks: `Dixon-\nColes` → `Dixon-Coles` only when the
     next line starts lowercase (preserves intentional line-end compounds).
   - Strip running headers/footers detected on ≥ 30% of pages.
   - Drop ToC dot-leader lines (chapter title + `......` + page number).
3. **Chapter assignment** — each page maps to the chapter whose `[page_start,
   page_end]` covers its printed page number.
4. **Paragraph segmentation** — chapter text is split on blank-line and heading
   boundaries. Paragraphs exceeding 1.5× the target token size are kept intact
   (oversized chunks acceptable; truncation would corrupt formulas and tables).
5. **Token-bucket chunking** — `tiktoken` (`cl100k_base`): target ~600 tokens,
   ~50-token overlap. Paragraphs are packed greedily until the next would
   exceed the target; emit the chunk; start the next with the last ~50 tokens
   of the previous for soft continuity.

Each chunk records `page_start` (first contributing page) and `page_end`
(last). Chunks are split at chapter edges so each chunk has exactly one
`chapter` value.

---

## Chunk metadata schema

<!-- code-ref: backend/app/core/rag/book_ingestion/chunker.py#BookChunker -->

All values are Chroma-compatible scalars (no nested types):

```python
{
    "book_slug":   "soccermatics",
    "book_title":  "Soccermatics: Mathematical Adventures in the Beautiful Game",
    "chapter":     "Chapter Eleven: Bet Against the Masses",
    "page_start":  197,
    "page_end":    200,
    "topic_tags":  "football,mathematics,poisson,dixon-coles,betting,market-efficiency",  # CSV
    "char_count":  2873,
    "token_count": 612,
    "chunk_index": 142,
}
```

Chunk ID format: `{book_slug}#{chunk_index:04d}` — e.g. `soccermatics#0142`.
Stable across reindex runs as long as the source PDF and manifest are
unchanged. `topic_tags` is a CSV string (Chroma scalar constraint); retriever
splits on `,` for downstream consumers.

---

## Hybrid retrieval: vector--BM25--RRF

<!-- code-ref: backend/app/core/rag/book_retriever.py#BookRetriever -->
<!-- code-ref: backend/app/core/rag/book_ingestion/bm25.py#Bm25Index -->

`BookRetriever.retrieve()` runs vector search and BM25 in parallel, then
fuses with **Reciprocal Rank Fusion** (default `k=60`):

```
score(doc) = Σ  1 / (k + rank_i(doc))   for i in {vector, bm25} if doc appears in i
```

Top-`top_k` results are sorted by fused score and returned as `BookSnippet`
objects.

**Why hybrid?** Vector search handles paraphrase and concept matching
("bookmaker's edge" → finds passages on vig/overround). BM25 handles
exact-term matching for domain-specific terms (`Dixon-Coles`, `Brier`,
`Kelly`, `Poisson-Gamma`) that embedding models often treat as
out-of-distribution.

**BM25 implementation.** `rank_bm25.BM25Okapi`. Tokeniser: NFKD lowercase +
`\b[a-z0-9-]{2,}\b` (preserves hyphenated terms, drops punctuation).
Index serialised to `/chroma/books_bm25.json`; loaded once at startup,
rebuilt on every full reindex.

**`where` filter.** `retrieve(query, where={"book_slug": "logic-of-sports-betting"})`
applies the filter to both vector and BM25 legs independently before fusion.
Single-book retrieval is a critical use case for Strategy implementations that
cite specific books.

**`namespace_filter`.** `retrieve(query, namespace_filter=["football", "statistics"])`
restricts both legs to chunks whose `namespace` metadata field is in the allow-list.
Chunks that lack the `namespace` field are excluded (Chroma's `$in` operator does
not match missing fields). Graceful degradation: pass `namespace_filter=None` for
corpora that have not yet been reingested with namespace tags.
When both `where` and `namespace_filter` are non-None, the two clauses are merged
into a single Chroma `$and` expression by the private `_build_where` helper.

---

## Public interface

<!-- code-ref: backend/app/core/rag/book_retriever.py#BookRetriever -->
<!-- code-ref: backend/app/core/rag/book_indexer.py#BooksIndexer -->

```python
@dataclass(frozen=True, slots=True)
class BookSnippet:
    book_slug:  str
    book_title: str
    chapter:    str
    page_start: int
    page_end:   int
    topic_tags: list[str]   # CSV split on retrieval
    text:       str
    score:      float       # RRF fused score
    chunk_id:   str


class BookRetriever:
    def __init__(
        self,
        *,
        collection: ChromaCollection,
        embedder: Embedder,
        bm25: Bm25Index,
    ) -> None: ...

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        where: dict | None = None,
        namespace_filter: list[str] | None = None,
        rrf_k: int = 60,
    ) -> list[BookSnippet]: ...


@dataclass(frozen=True, slots=True)
class ReindexReport:
    books_processed:   int
    chapters_processed: int
    chunks_upserted:   int
    orphans_swept:     int
    bm25_terms:        int
    duration_seconds:  float


class BooksIndexer:
    def __init__(
        self,
        *,
        config: RagConfig,
        books_root: Path,
        manifests: list[BookManifest],
        collection: ChromaCollection,
        embedder: Embedder,
        bm25_sidecar_path: Path,
    ) -> None: ...

    def reindex(self) -> ReindexReport: ...
```

---

## Configuration

<!-- code-ref: backend/app/core/rag/book_indexer.py#BooksIndexer -->

`config/rag.yaml` includes a `books` collection block:

```yaml
collections:
  books:
    name: portal_books
    books_root: /data/books           # mounted from PORTAL_BOOKS_DIR
    manifests_glob: "config/books/*.yaml"
    bm25_sidecar_path: /chroma/books_bm25.json
    chunk_target_tokens: 600
    chunk_overlap_tokens: 50
```

`PORTAL_BOOKS_DIR` in `.env` points to the host path containing the PDFs
(e.g. `~/Sites/Books`). The scheduler service mounts it as
`/data/books`. The `manifests_glob` is resolved relative to the repo root
(`PORTAL_REPO_ROOT`).

---

## Boot-time guard--CLI shim

<!-- code-ref: backend/app/core/rag/tasks/index_books.py#ensure_books_indexed -->
<!-- code-ref: backend/app/rag/index_books.py -->

`ensure_books_indexed(repo_root)` mirrors `ensure_docs_indexed()` exactly:

1. Read the `portal_books` collection; check `__meta__/embedding_model` sentinel.
2. If sentinel matches current model **and** collection has ≥ 1 non-sentinel
   chunk, skip (log "books indexed — skip").
3. If sentinel differs, force full reindex (all chunks deleted first).
4. Call `BooksIndexer.reindex()` and log the `ReindexReport`.

Hooked into `app/scheduler_entry.py` immediately after `ensure_docs_indexed()`.
No cron registration — books are static; reindex only runs at boot or when
the operator explicitly clears the collection.

CLI shim: `python -m app.rag.index_books` calls `BooksIndexer.reindex()`
directly. Useful for ad-hoc reruns when a manifest changes without a full
container restart.

---

## OCR for Fixed Odds Sports Betting

The `fixed-odds-sports-betting` manifest sets `needs_ocr: true` because this
PDF is image-only (0 extractable text characters). When `PdfExtractor`
encounters `needs_ocr: true` and all pages return < 50 chars, it raises:

```
OcrRequiredError:
  ocrmypdf /data/books/fixed-odds-sports-betting.pdf \
           /data/books/fixed-odds-sports-betting.ocr.pdf
```

Run this command once on the host (`ocrmypdf` + Tesseract required). After
the OCR'd file exists, update `source_pdf` in the manifest to point to the
`.ocr.pdf` file, or replace the original manually. Subsequent extraction
returns normal text.

---

## Appendix — Chunks audit

An earlier iteration generated ad-hoc chunks via standalone `pdf.py` and
`chunks.py` scripts, producing artefacts in local `txt_books/` and
`chunks/` directories. These were
discarded for the following reasons:

- **No structural metadata.** Chunks carried only `chunk_id` and `text`.
  No book identifier, chapter, page range, or topic tags; retrieval could
  not answer "which book said this?" and `where`-filter queries were impossible.
- **Pure character-based sliding window.** ~1000-char chunks with fixed
  overlap, ignoring paragraph boundaries, table layout, and chapter
  transitions. Many chunks split mid-sentence or merged two unrelated topics.
- **Text not normalised.** PDF ligatures and hyphenation breaks were embedded
  as-is, degrading both embedding quality and BM25 token matching.
- **Table-of-contents leaked.** ToC dot-leaders appeared inside chunks and
  dominated token statistics.
- **Fixed Odds Sports Betting is image-only.** PyMuPDF returned 223 blank
  bytes per page; the resulting txt file was empty.

This business-logic doc and the corresponding pipeline rebuild chunking from
scratch with full metadata. (Audit deliverable for issue #209.)
