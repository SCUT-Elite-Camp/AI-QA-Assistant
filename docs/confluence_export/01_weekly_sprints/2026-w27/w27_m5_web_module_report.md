# [2026-W27] Web Module (UI & Full-stack Gateway) Weekly Deliverable Report

> **Sprint Period**: 2026-06-29 to 2026-07-05 | **Module**: `web`
> **Contributors**: YourGitHubUsername, cheng-sh | **Status**: 🟢 Completed

---

## 1. Executive Summary
This report details the work delivered for the **Web Module (UI & Full-stack Gateway)** during **2026-W27**.
**Module Scope**: Frontend UI components, chat view, document viewer, settings drawer, and server-side API proxy.

### Key Highlights & Deliverables
- **Total Commits**: 2
- **New Features Delivered**: 2
- **Bug Fixes Resolved**: 0
- **Other Improvements**: 0

## 2. Work Breakdown & Deliverables

### 🚀 New Features & Enhancements
- **`d689c50e1`** - feat(web): add e2e tests, english error messages, and playwright config *(by @cheng-sh on 2026-07-03)*
- **`0c9933872`** - feat: implement automatic RAG model preloading on startup and fix Vercel AI SDK stream serialization format *(by @YourGitHubUsername on 2026-07-04)*

## 3. Impacted Code Files
| Action | File Path |
| :--- | :--- |
| `MODIFIED` | `"docs/\346\225\260\346\215\256\345\244\204\347\220\206\347\256\241\347\272\277\350\257\246\350\247\243.md"	"data-pipeline/docs/\346\225\260\346\215\256\345\244\204\347\220\206\347\256\241\347\272\277\350\257\246\350\247\243.md"` |
| `MODIFIED` | `.gitignore` |
| `DELETED` | `agent/.gitignore` |
| `MODIFIED` | `agent/agent/config/settings.py` |
| `MODIFIED` | `agent/app.py` |
| `DELETED` | `agent/requirements.txt` |
| `ADDED` | `agent/tests/conftest.py` |
| `MODIFIED` | `agent/tests/integration/test_tool_layer_smoke.py` |
| `DELETED` | `agent/tool_layer/__init__.py` |
| `DELETED` | `agent/tool_layer/search_tool.py` |
| `DELETED` | `data-persistence/.gitignore` |
| `DELETED` | `data-persistence/requirements.txt` |
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
| `ADDED` | `data-pipeline/models/document.py` |
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
| `MODIFIED` | `toolset/tool_layer/search_tool.py` |
| `DELETED` | `web/.gitignore` |
| `ADDED` | `web/e2e/chat-management.spec.ts` |
| `ADDED` | `web/e2e/edge-cases.spec.ts` |
| `ADDED` | `web/e2e/error-display.spec.ts` |
| `ADDED` | `web/e2e/home-navigation.spec.ts` |
| `ADDED` | `web/e2e/message-actions.spec.ts` |
| `ADDED` | `web/e2e/normal-chat.spec.ts` |
| `ADDED` | `web/package-lock.json` |
| `MODIFIED` | `web/package.json` |
| `ADDED` | `web/playwright.config.ts` |
| `MODIFIED` | `web/server/routes/api/chats/[id].post.ts` |
| `MODIFIED` | `web/src/mock/errorMap.ts` |
| `MODIFIED` | `web/src/pages/chat/[id].vue` |

## 4. Git Commit Verification Log
| Short Hash | Author | Date | Category | Commit Message |
| :--- | :--- | :--- | :--- | :--- |
| `d689c50e1` | cheng-sh | 2026-07-03 | `Feature` | feat(web): add e2e tests, english error messages, and playwright config |
| `0c9933872` | YourGitHubUsername | 2026-07-04 | `Feature` | feat: implement automatic RAG model preloading on startup and fix Vercel AI SDK stream serialization format |

---
## 5. Next Sprint Outlook
- Continue integration and refinement based on cross-module milestones.
- Address feedback and optimize test coverage for modified files.
