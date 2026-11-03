# RAG pipeline from a sports analytics platform I built

These files are copied from a running system: a FastAPI + Angular platform
with a ChromaDB retrieval layer, deployed via Docker Compose. Comments and docstrings
are as they exist in the repo.

## Stack

| Layer | Tech |
|---|---|
| Vector DB | ChromaDB (own service in the compose stack), 6 collections |
| Embeddings | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 384-dim, local via fastembed/ONNX |
| Keyword leg | `rank_bm25.BM25Okapi`, JSON sidecar rebuilt on reindex |
| Fusion | Reciprocal Rank Fusion, k=60 |
| Orchestration | LangGraph (retrieve → decide → web search → compose) |
| LLM | Provider-abstracted and swappable via `config/llm.yaml` (Anthropic / OpenAI / Ollama) |
| PDF ingestion | PyMuPDF + tiktoken token-bucket chunking |
| Backend | FastAPI, Python 3.12, pytest |

Collections in production: `portal_docs`, `portal_code`, `portal_specs`, `portal_kb`,
`portal_tickets` (sourced from MySQL, not the filesystem), `portal_books`.

## Files

| File | What it demonstrates |
|---|---|
| `01_hybrid_retrieval_rrf.py` | Hybrid vector + BM25 retrieval fused with RRF. Filter consistency across both legs, over-fetch per leg, metadata backfill for BM25-only hits. |
| `02_bm25_sidecar.py` | BM25 index: tokeniser that preserves hyphenated domain terms, serialisation, filtered query, degenerate-corpus guards. |
| `03_pdf_page_normalisation.py` | The ingestion cleanup that mattered most for precision: ligature folding, de-hyphenation, running-header detection, ToC dot-leader removal. |
| `04_token_aware_chunker.py` | Token-budget chunking (~600 tok, ~50 tok overlap) that never splits mid-paragraph and never crosses a chapter boundary. |
| `05_incremental_indexer.py` | Idempotent reindex: content-addressed chunk IDs, batched embed+upsert, orphan sweep, heading-path prepended before embedding. |
| `06_embedding_model_sentinel.py` | Per-collection sentinel recording which embedding model produced the vectors; forces a full reindex on model change. |
| `07_langgraph_rag_nodes.py` | LangGraph nodes. Note `decide_node`: the distance/zero-hit/freshness gate that routes weak retrieval to web search instead of letting the LLM improvise. |
| `08_namespaced_retrieval_cache.py` | Namespace-filtered retrieval for the LLM decision engine, with a cache keyed on (version, corpus hash, template hash) so it invalidates correctly on reingest or prompt edits. |
| `09_test_hybrid_retrieval.py` | Retrieval tests against stub Chroma/embedder. ~164 tests cover the retrieval + ingestion layers overall. |
| `10_rag_config.yaml` | The live retrieval config — collections, globs, chunkers, embedding model, batch sizes. No hardcoded tunables anywhere in the code. |
| `11_design_doc_book_rag.md` | The internal design doc for the book corpus: chunk metadata schema, hybrid retrieval rationale, and an audit of why the previous naive character-window chunking was thrown away. |

## Suggested reading order

`11` (context) → `01` (retrieval core) → `03` + `04` (why precision improved) → `07`
(hallucination gating) → `05` + `06` (operational correctness).
