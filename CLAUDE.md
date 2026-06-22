# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RAGent is an enterprise knowledge base Q&A system based on RAG (Retrieval Augmented Generation). The Q1 phase aims to deliver a single-turn Q&A pipeline: user question → document retrieval → answer generation → citation display.

**Tech stack:** Python/Flask backend, Vue 3 frontend, Milvus vector database (Docker), OpenAI-compatible embedding + LLM APIs, jieba + BM25 for keyword retrieval, RRF for hybrid fusion.

## Commands

### Start Milvus (required for most operations)
```bash
docker-compose up -d
```

### Install Python dependencies (uv 管理)
```bash
uv sync                       # 安装所有依赖
uv pip install -r requirements.txt  # 或从旧 requirements.txt 安装
```

Required env vars before running the pipeline or agent:
```bash
export OPENAI_API_KEY="sk-..."
export OPENAI_BASE_URL="https://api.deepseek.com/v1"  # 可选，兼容 DeepSeek 等
```

### Data Processing Pipeline
```bash
# 处理文件夹中的所有 PDF/DOCX → 切片 → 向量化 → 存入 Milvus + JSON + BM25 索引
python -m pipeline.process data/raws/测试空间

# 自定义分块参数
python -m pipeline.process data/raws/测试空间 --chunk-size 500 --overlap 100
```

### Run tests
```bash
# Run all tests (storage tests auto-skip if Milvus is not running)
pytest tests/ -v

# Run a single test file
pytest tests/test_storage.py -v

# Run a specific test
pytest tests/test_storage.py::test_document_store -v
```

Tests use `pytest.mark.skipif` with automatic Milvus availability detection — if Docker is not running, vector store tests are skipped gracefully.

## Architecture

### Data Flow (Q1 target)
```
Raw docs (data/raws/) → Parsers → Chunker → Embedder → Milvus (vectors) + JSON files (metadata)
                                                    ↘ BM25 Index (data/bm25_index.pkl)
User question → Hybrid Search (Vector + BM25 → RRF) → LLM with prompt → Streamed SSE response
```

### Current Implementation Status

**Implemented:**
- `models/document.py` — Pydantic `Document` and `Chunk` models. `doc_id` is MD5 of absolute file path for idempotent processing.
- `parsers/` — `PDFParser` (pymupdf), `DocxParser` (python-docx), registry/factory in `registry.py`.
- `pipeline/chunker.py` — Character-based overlapping chunking (default 500 chars, 100 overlap).
- `pipeline/embedder.py` — OpenAI `text-embedding-3-small` wrapper (1536-dim). Reads `OPENAI_API_KEY` and `OPENAI_BASE_URL` from env.
- `pipeline/process.py` — `process_folder()` orchestrates: scan → parse → chunk → embed → save JSON → insert Milvus → build BM25.
- `retrieval/bm25_index.py` — `BM25Index` with jieba tokenization + BM25Okapi. Build from `data/documents/`, persist to `data/bm25_index.pkl`.
- `storage/` — `MilvusStore` (HNSW + IP metric, insert/search/filter/delete), `document_store.py` (local JSON CRUD).
- `tests/test_storage.py` — Comprehensive storage layer tests with end-to-end integration.

**Scaffold only (empty files, yet to implement):**
- `retrieval/search.py` — Hybrid search combining Milvus vector search + BM25 keyword search + RRF fusion
- `agent/` — RAG agent loop, LLM inference engine, hallucination-suppression prompt template
- `server/` — Flask SSE streaming API
- `frontend/` — Vue 3 SPA with chat interface

### Key Design Decisions

- **Milvus collection schema**: Fields include `id` (auto int), `embedding` (float vector), `chunk_id`, `chunk_text` (up to 65535 chars), `doc_id`, `chunk_index`, `source_url`. Primary key is auto-generated.
- **Vector index**: HNSW with inner product (IP) metric, M=16, efConstruction=200, nprobe=10 for search.
- **Document storage**: JSON files keyed by `doc_id` under `./data/documents/`. The retrieval flow uses `doc_id` from Milvus results to look up full document metadata from JSON.
- **doc_id generation**: MD5 hash of absolute file path — ensures idempotent processing (re-running the pipeline on the same files won't create duplicates).
- **Chunk ID format**: `{doc_id}_chunk_{index}`, globally unique across all documents.
- **Chunking**: Character-based with 500 char default size and 100 char overlap. Same chunks serve both Milvus (via embeddings) and BM25 (via jieba tokenization).
- **BM25**: BM25Okapi from `rank_bm25`, cannot incrementally update — full rebuild on each pipeline run. Index persisted via pickle to `data/bm25_index.pkl`.
- **Testing pattern**: Milvus availability is probed at module load (`timeout=2.0s`), and vector-dependent tests use `@pytest.mark.skipif` to gracefully skip when Docker is not running. Tests clean up their own collections.
