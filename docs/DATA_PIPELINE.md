# 当前数据处理管线

更新：2026-10-12。`table-processing` 整合到 `optimization` 后的接口与运行约定。
访问权限、版本/hash 和证据释放仍以[访问架构](access-evidence-architecture.md)及
[接入契约](access-evidence-integration.md)为准。

## 解析、切块和索引

`parsers.registry.parse_file(path)` 返回 `list[Document]`，保留 PDF、DOCX、DOC、PPTX、
HTML/HTM、Markdown 和 XLSX 入口；HTML 可以产出主文档及多个附件文档。
`PDFParser`、`DocxParser`、`XlsxParser` 的直接 `parse()` 调用仍返回单个 Document。
解析器包保持按需导入，可选表格模型不成为普通模块导入的必需依赖。

DOCX/XLSX 通过原生单元格信息保存合并单元格、复合表头和工作表 caption。
PDF 按坐标重建阅读顺序，识别重复页眉/页脚，按区域融合原生文字与 OCR；
解析决定、后端错误和表格数量保存到 `Document.parse_diagnostics`。

PDF 表格由 PyMuPDF、可选 Camelot、PaddleOCR 和 GMFT 后端路由、评分。
`accepted` 表格进入正文和索引；`review` 对象留在 JSON 供诊断，其不确定单元格不进入
索引，PDF 原生正文继续保留；`rejected` 表格丢弃。

`pipeline.structured_ingestion.prepare_ingestion_chunks()` 是共享切块入口。
全量 `process_folder()`、增量 `auto_process_raws()` 和定向 `process_specific_files()`
通过 `_index_document()` 复用 Evidence/Section 双集合写入与 JSON 保存顺序。
PDF 评估脚本复用同一切块入口，不执行 embedding 或 Milvus 写入。

每个 Chunk 同时保留 `index_text` 与 `markdown_text`；向量和 BM25 使用语义文本，
模型上下文及展示保留 Markdown。`text` 保持展示文本的兼容语义；旧 JSON 自动从
`text` 补齐新字段。结构化表格生成整表及带表头的行级检索片段。
Wiki 理解只消费原始整表的精确 Evidence span，跳过重复的行视图；在线 Wiki 导航
仍受既有 lineage 隔离约束，本次整合没有开启导航授权。

## 溯源与旧集合兼容

ContentBlock、TableArtifact 和 Chunk 可以携带 block/table ID、页码、bbox、来源及置信度。
跨页 Chunk 用 `source_pages` 和 `page_regions` 保存各页真实坐标，标量页码/bbox 为空；
Milvus 无页码写 0。区域 JSON 使用 `[x0,y0,x1,y1]` 数组，不把不同页坐标合成单个区域。
没有可靠 bbox 时保留页码信息，但不生成假的区域。

新 Milvus 集合在现有 `title`、`space`、`doc_type` 等字段上增加：

| 字段 | 类型 |
| --- | --- |
| `chunk_type` | VARCHAR(64) |
| `block_id`、`table_id` | VARCHAR(1024) |
| `page_number` | INT64 |
| `bbox_json` | VARCHAR(256) |
| `metadata_json` | VARCHAR(65535) |

新 schema 写入前必须通过 `validate_chunk_schema()`；主管线在删除旧向量前执行检查。
旧集合的已有读取继续可用，查询只请求实际存在的字段；写入结构化溯源时，旧 schema
会明确失败，要求使用新的集合或维护重建。不会自动修改、删除或重建旧集合。
保留 `MILVUS_HOST/PORT/COLLECTION`、连接/搜索超时、实际向量维度检查、空授权集合拒绝、
doc ID 交集和 `space/doc_type/chunk_ids` 过滤。

SearchTool 最终返回的表格类型及 page regions 来自当前 JSON 投影，必须先与命中的
chunk 原文匹配。过期向量中的几何信息不能获得当前 source version/hash。
BM25 只读取明确指定的 documents directory，避免混入另一份全局投影。

## OCR 与可选依赖

基础依赖仍为根 `requirements.txt`。按需要安装 `requirements-table-pdf.txt`
（Camelot/GMFT）或 `requirements-table-ocr.txt`（PaddleOCR/PaddlePaddle）。
通用正文 OCR 使用 PyMuPDF 的 Tesseract 后端，需要本机 Tesseract 和语言数据；
不自动安装语言包或模型。缺后端/语言或执行失败会记录诊断，并保留可读取的原生文字。

| 设置 | 用途 |
| --- | --- |
| `PDF_OCR_LANGUAGES` | 默认 `chi_sim+eng`；按已安装语言有界降级 |
| `PDF_OCR_DPI` | 72–600，默认 300 |
| `AI_QA_DATA_DIR` | raw 文件和权威 documents 根目录 |
| `BM25_INDEX_PATH` | BM25 索引路径，可在数据根目录外 |
| `MILVUS_COLLECTION` | 企业 Evidence 集合 |
| `SECTION_MILVUS_COLLECTION` | 独立 Section 集合，默认 `document_sections_bgem3` |

这套结构化解析器服务于企业离线管线；私有附件服务仍使用自身解析器与独立存储/权限。
本次没有改变附件服务身份、有效期、解析协议或恢复已移除的病毒扫描。

## 维护工具

所有运行数据、源文件、模型和真实验收产物都应位于 checkout 外。
联调时 `RESEARCH_DOCUMENTS_DIR` 必须与 `AI_QA_DATA_DIR/documents` 指向同一份权威正文。
优先使用新目录与新 Evidence/Section 集合，验证后再按运行手册切换服务配置。

`python scripts/safe_reindex.py` 默认仅预检，列出源文件、配置集合、备份目标及子进程命令。
需要维护已有指定集合时，停写后使用 `--execute --confirm REBUILD`：包装器备份 documents
和 BM25，将指定 Evidence/Section 集合改名为备份，再执行强制、严格重建；错误会回滚，
成功保留 `.reindex-backups/<UTC时间戳>` 与备份集合供核验。子进程使用同一 host/port、
集合和目录配置，不处理 knowledge_cards、semantic_segments、私有集合或原始文件。
`scripts/reindex.py` 要求 `--confirm REBUILD`，直接执行没有包装层的回滚保证。
此流程属于停写维护操作；遇到回滚错误应使用保留备份人工恢复，不宣称在线原子切换。

只读检查：`python scripts/check_milvus_provenance.py --host HOST --port PORT --collection NAME`。
它检查已有 schema 和样本，不创建或替换集合；默认值跟随 Milvus 环境配置。
解析报告：`python scripts/evaluate_pdf_parsing.py <PDF文件或目录> --output <checkout外报告>`，
可加 `--expectations <JSON>` 检查所需文字与最少表格数量。

测试与本轮限制见[整合记录](table-processing-integration-20261012.md)。解析测试或生成的
本地 PDF 冒烟测试不等于真实模型、embedding/Milvus、原生权限与 BFF 的产品验收。
