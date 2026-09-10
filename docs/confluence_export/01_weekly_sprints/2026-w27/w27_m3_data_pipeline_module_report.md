# [2026-W27] Data Pipeline Module (Crawling & Processing) Weekly Deliverable Report

> **Sprint Period**: 2026-06-29 to 2026-07-05 | **Module**: `data-pipeline`
> **Contributors**: YourGitHubUsername | **Status**: 🟢 Completed

---

## 1. Executive Summary
This report details the work delivered for the **Data Pipeline Module (Crawling & Processing)** during **2026-W27**.
**Module Scope**: Document ingestion, Confluence/HTML crawler, text cleaning, chunking, and embedding preparation.

### Key Highlights & Deliverables
- **Total Commits**: 4
- **New Features Delivered**: 1
- **Bug Fixes Resolved**: 0
- **Other Improvements**: 3

## 2. Work Breakdown & Deliverables

### 🚀 New Features & Enhancements
- **`0c9933872`** - feat: implement automatic RAG model preloading on startup and fix Vercel AI SDK stream serialization format *(by @YourGitHubUsername on 2026-07-04)*

### 🛠️ Refactoring & Engineering Tasks
- **`8f804f099`** - refactor: abstract high-level DocumentParser class in data-pipeline parsers *(by @YourGitHubUsername on 2026-07-04)*
- **`64b357c8b`** - refactor: optimize project structures, decouple modules, remove redundant code across all layers *(by @YourGitHubUsername on 2026-07-05)*
- **`a7396869b`** - refactor: move retrieval package from data-pipeline to toolset, ensure data-pipeline is clean of retrieval logic *(by @YourGitHubUsername on 2026-07-05)*

## 3. Impacted Code Files
| Action | File Path |
| :--- | :--- |
| `MODIFIED` | `"docs/\346\225\260\346\215\256\345\244\204\347\220\206\347\256\241\347\272\277\350\257\246\350\247\243.md"	"data-pipeline/docs/\346\225\260\346\215\256\345\244\204\347\220\206\347\256\241\347\272\277\350\257\246\350\247\243.md"` |
| `MODIFIED` | `.gitignore` |
| `DELETED` | `agent/.gitignore` |
| `MODIFIED` | `agent/agent/api/chat_routes.py` |
| `MODIFIED` | `agent/agent/config/settings.py` |
| `MODIFIED` | `agent/agent/errors/exceptions.py` |
| `MODIFIED` | `agent/agent/logger/__init__.py` |
| `MODIFIED` | `agent/agent/logger/app_logger.py` |
| `MODIFIED` | `agent/agent/logger/logger.py` |
| `MODIFIED` | `agent/agent/prompt/prompt_builder.py` |
| `MODIFIED` | `agent/agent/retrieval/retrieval_adapter.py` |
| `MODIFIED` | `agent/agent/schemas/common.py` |
| `MODIFIED` | `agent/agent/service/chat_service.py` |
| `MODIFIED` | `agent/app.py` |
| `MODIFIED` | `agent/pytest.ini` |
| `DELETED` | `agent/requirements.txt` |
| `ADDED` | `agent/tests/conftest.py` |
| `MODIFIED` | `agent/tests/integration/test_tool_layer_smoke.py` |
| `DELETED` | `agent/tool_layer/__init__.py` |
| `DELETED` | `agent/tool_layer/search_tool.py` |
| `DELETED` | `data-persistence/.gitignore` |
| `DELETED` | `data-persistence/requirements.txt` |
| `MODIFIED` | `data-persistence/storage/document_store.py` |
| `MODIFIED` | `data-persistence/storage/milvus_store.py` |
| `ADDED` | `data-persistence/tests/conftest.py` |
| `MODIFIED` | `data-persistence/tests/test_storage.py` |
| `DELETED` | `data-persistence/volumes/etcd/member/snap/db` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data/000005.log` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data/000012.log` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data/000016.sst` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data/000018.log` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data/CURRENT` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data/IDENTITY` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data/LOCK` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data/LOG` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data/LOG.old.1780928432968569` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data/LOG.old.1780929067551762` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data/MANIFEST-000011` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data/MANIFEST-000015` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data/MANIFEST-000017` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data/OPTIONS-000009` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data/OPTIONS-000014` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data_meta_kv/000009.sst` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data_meta_kv/000015.sst` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data_meta_kv/000017.log` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data_meta_kv/CURRENT` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data_meta_kv/IDENTITY` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data_meta_kv/LOCK` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data_meta_kv/LOG` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data_meta_kv/LOG.old.1780928432615642` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data_meta_kv/LOG.old.1780929067241706` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data_meta_kv/MANIFEST-000016` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data_meta_kv/OPTIONS-000013` |
| `DELETED` | `data-persistence/volumes/milvus/rdb_data_meta_kv/OPTIONS-000019` |
| `DELETED` | `data-persistence/volumes/minio/.minio.sys/buckets/.bloomcycle.bin/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/.minio.sys/buckets/.usage-cache.bin/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/.minio.sys/buckets/.usage.json/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/.minio.sys/buckets/a-bucket/.metadata.bin/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/.minio.sys/buckets/a-bucket/.usage-cache.bin/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/.minio.sys/config/config.json/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/.minio.sys/config/iam/format.json/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/.minio.sys/format.json` |
| `DELETED` | `data-persistence/volumes/minio/.minio.sys/pool.bin/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/.minio.sys/tmp/.trash/4408655b-90db-455c-8045-7105a752b08c` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210082393/466859703210082394/466859703210282428/0/466859703210282439/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210082393/466859703210082394/466859703210282428/1/466859703210282440/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210082393/466859703210082394/466859703210282428/100/466859703210282433/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210082393/466859703210082394/466859703210282428/101/466859703210282434/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210082393/466859703210082394/466859703210282428/102/466859703210282435/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210082393/466859703210082394/466859703210282428/103/466859703210282436/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210082393/466859703210082394/466859703210282428/104/466859703210282437/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210082393/466859703210082394/466859703210282428/105/466859703210282438/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210482471/466859703210482472/466859703210482502/0/466859703210282448/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210482471/466859703210482472/466859703210482502/1/466859703210282449/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210482471/466859703210482472/466859703210482502/100/466859703210282442/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210482471/466859703210482472/466859703210482502/101/466859703210282443/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210482471/466859703210482472/466859703210482502/102/466859703210282444/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210482471/466859703210482472/466859703210482502/103/466859703210282445/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210482471/466859703210482472/466859703210482502/104/466859703210282446/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210482471/466859703210482472/466859703210482502/105/466859703210282447/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210482672/466859703210482673/466859703210482708/0/466859703210282457/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210482672/466859703210482673/466859703210482708/1/466859703210282458/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210482672/466859703210482673/466859703210482708/100/466859703210282451/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210482672/466859703210482673/466859703210482708/101/466859703210282452/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210482672/466859703210482673/466859703210482708/102/466859703210282453/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210482672/466859703210482673/466859703210482708/103/466859703210282454/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210482672/466859703210482673/466859703210482708/104/466859703210282455/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210482672/466859703210482673/466859703210482708/105/466859703210282456/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210482751/466859703210482752/466859703210482782/0/466859703210282466/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210482751/466859703210482752/466859703210482782/1/466859703210282467/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210482751/466859703210482752/466859703210482782/100/466859703210282460/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210482751/466859703210482752/466859703210482782/101/466859703210282461/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210482751/466859703210482752/466859703210482782/102/466859703210282462/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210482751/466859703210482752/466859703210482782/103/466859703210282463/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210482751/466859703210482752/466859703210482782/104/466859703210282464/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/insert_log/466859703210482751/466859703210482752/466859703210482782/105/466859703210282465/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/stats_log/466859703210082393/466859703210082394/466859703210282428/100/1/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/stats_log/466859703210082393/466859703210082394/466859703210282428/100/466859703210282441/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/stats_log/466859703210482471/466859703210482472/466859703210482502/100/1/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/stats_log/466859703210482471/466859703210482472/466859703210482502/100/466859703210282450/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/stats_log/466859703210482672/466859703210482673/466859703210482708/100/1/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/stats_log/466859703210482672/466859703210482673/466859703210482708/100/466859703210282459/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/stats_log/466859703210482751/466859703210482752/466859703210482782/100/1/xl.meta` |
| `DELETED` | `data-persistence/volumes/minio/a-bucket/files/stats_log/466859703210482751/466859703210482752/466859703210482782/100/466859703210282468/xl.meta` |
| `ADDED` | `data-pipeline/models/__init__.py` |
| `MODIFIED` | `data-pipeline/models/document.py` |
| `MODIFIED` | `data-pipeline/parsers/__init__.py` |
| `MODIFIED` | `data-pipeline/parsers/docx_parser.py` |
| `MODIFIED` | `data-pipeline/parsers/pdf_parser.py` |
| `MODIFIED` | `data-pipeline/parsers/registry.py` |
| `MODIFIED` | `data-pipeline/pipeline/chunker.py` |
| `MODIFIED` | `data-pipeline/pipeline/embedder.py` |
| `MODIFIED` | `data-pipeline/pipeline/process.py` |
| `MODIFIED` | `data-pipeline/retrieval/__init__.py	toolset/retrieval/__init__.py` |
| `MODIFIED` | `data-pipeline/retrieval/bm25_index.py` |
| `MODIFIED` | `data-pipeline/retrieval/bm25_index.py	toolset/retrieval/bm25_index.py` |
| `DELETED` | `data-pipeline/retrieval/search.py` |
| `MODIFIED` | `parsers/__init__.py	data-pipeline/parsers/__init__.py` |
| `MODIFIED` | `parsers/base.py	data-pipeline/parsers/base.py` |
| `MODIFIED` | `parsers/docx_parser.py	data-pipeline/parsers/docx_parser.py` |
| `MODIFIED` | `parsers/pdf_parser.py	data-pipeline/parsers/pdf_parser.py` |
| `MODIFIED` | `parsers/registry.py	data-pipeline/parsers/registry.py` |
| `MODIFIED` | `pipeline/__init__.py	data-pipeline/pipeline/__init__.py` |
| `MODIFIED` | `pipeline/chunker.py	data-pipeline/pipeline/chunker.py` |
| `MODIFIED` | `pipeline/embedder.py	data-pipeline/pipeline/embedder.py` |
| `MODIFIED` | `pipeline/process.py	data-pipeline/pipeline/process.py` |
| `ADDED` | `requirements.txt` |
| `MODIFIED` | `retrieval/__init__.py	data-pipeline/retrieval/__init__.py` |
| `MODIFIED` | `retrieval/bm25_index.py	data-pipeline/retrieval/bm25_index.py` |
| `MODIFIED` | `retrieval/search.py	data-pipeline/retrieval/search.py` |
| `ADDED` | `start_project.py` |
| `DELETED` | `toolset/agent_layer/__init__.py` |
| `DELETED` | `toolset/agent_layer/simple_rag_agent.py` |
| `DELETED` | `toolset/data/chunks.jsonl` |
| `DELETED` | `toolset/data/documents/agent_integration_notes.json` |
| `DELETED` | `toolset/data/documents/config_demo_doc.json` |
| `DELETED` | `toolset/data/documents/cp3_reliability_plan.json` |
| `DELETED` | `toolset/data/documents/milvus_backend_plan.json` |
| `DELETED` | `toolset/data/documents/pipeline_chunk_contract.json` |
| `DELETED` | `toolset/data/documents/tool_cp2_design.json` |
| `DELETED` | `toolset/data/documents/web_citation_demo.json` |
| `DELETED` | `toolset/data/eval_questions.json` |
| `DELETED` | `toolset/demo_cp4_agent_integration.py` |
| `DELETED` | `toolset/docs/cp3_demo_slides.pptx` |
| `DELETED` | `toolset/docs/requirements.md` |
| `ADDED` | `toolset/tests/conftest.py` |
| `DELETED` | `toolset/tests/test_simple_rag_agent.py` |
| `MODIFIED` | `toolset/tool_layer/search_tool.py` |
| `DELETED` | `web/.gitignore` |
| `ADDED` | `web/package-lock.json` |
| `MODIFIED` | `web/server/routes/api/chats/[id].post.ts` |

## 4. Git Commit Verification Log
| Short Hash | Author | Date | Category | Commit Message |
| :--- | :--- | :--- | :--- | :--- |
| `0c9933872` | YourGitHubUsername | 2026-07-04 | `Feature` | feat: implement automatic RAG model preloading on startup and fix Vercel AI SDK stream serialization format |
| `8f804f099` | YourGitHubUsername | 2026-07-04 | `Refactoring` | refactor: abstract high-level DocumentParser class in data-pipeline parsers |
| `64b357c8b` | YourGitHubUsername | 2026-07-05 | `Refactoring` | refactor: optimize project structures, decouple modules, remove redundant code across all layers |
| `a7396869b` | YourGitHubUsername | 2026-07-05 | `Refactoring` | refactor: move retrieval package from data-pipeline to toolset, ensure data-pipeline is clean of retrieval logic |

---
## 5. Next Sprint Outlook
- Continue integration and refinement based on cross-module milestones.
- Address feedback and optimize test coverage for modified files.
