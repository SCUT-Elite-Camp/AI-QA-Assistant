# 当前数据处理管线

## 2026-10-16 分块与重排更新

共享准备入口默认正文目标从 500 字符调整为 2000 字符，再按 `CHUNK_MAX_TOKENS=320`
的实际 embedding tokenizer 预算切分，优先句子与空白边界。`--chunk-size` 仍是字符目标，
不是 token 数。`CHUNK_TOKENIZER_PATH` 可指定离线 tokenizer.json；缺少本地 tokenizer
时使用更保守的字符计数，chunk metadata 明确标记。标题和章节路径进入 index_text，
正文仍保持原文；同章节的 previous/next chunk ID、原 block 范围保留在 metadata 中。

表格不再为每一行复制整表：小表保留一份完整表，较大表按行组保留表头；极宽单行
按带行标识和列名的字段组拆分。同一行的字段尽量放在同一片段，而非一字段一块。
相邻、显式以 Units:/All amounts/Note:/Source: 等开头的短说明会关联到各个行组，
并记录 context_block_ids 和来源区域；任意附近正文不会被当成单位或脚注。
表头恢复记录 header_inferred，数字数据开始后不把后续说明行提升为表头。
`row_start`/`row_end` 为原表零基行范围，原 TableArtifact
和 cell geometry 继续保存在文档投影中。模型看到的是有界证据，不是截断整表。
XLSX 同时读取公式和已有缓存值，TableCell 的 formula/cached_value 保留两种表示；
无缓存时显示 result unavailable，不执行公式、不伪造结果。PDF 原生裁剪字符顺序只在
与表格提取的字符集合一致时替换，用于保留下划线等易被版面排序移动的字符。

这些变更需要重建 BM25 和向量集合。仅改代码不会修复既有 chunk。使用独立输出目录
和集合验证，再明确决定是否切换；不要原地覆盖原索引。可用
`python eval/retrieval_rerank_probe.py --cases <frozen.json> --output-dir <outside-checkout>`
产生 A/B/C/D 组件对照原始证据，按质量政策由 Codex 逐事实复核；此命令不运行回答模型，
不代表原生权限或 BFF 验收。

更新：2026-10-15。当前共享管线的目录、接口与运行约定。
访问权限、版本/hash 和证据释放仍以[访问架构](../access-evidence/access-evidence-architecture.md)及
[接入契约](../access-evidence/access-evidence-integration.md)为准。

## 目录与入口

```text
pipeline/
  entrypoints/   # 选择文件：全量目录、增量、指定文件
  documents/     # 切块、章节树、章节标识规则
  files/         # 解析、超时、校验、预览、上下文和证据格式适配
  confluence/    # 导出快照、传输、来源撤回
  ingestion/     # 公共批处理、文档准备、投影发布和上传任务状态
  indexing/      # embedding、向量序列化/写入、独立 worker
  wiki/          # 已有 Wiki 派生处理；在线导航仍受 lineage 隔离约束
```

三个入口只选择输入文件：`pipeline.entrypoints.process` 处理目录；
`pipeline.entrypoints.auto_process` 选择变更文件和确认撤回项；
`pipeline.entrypoints.process_specific_files` 接收指定文件。
它们统一调用 `pipeline.ingestion.batch.run_batch()`，复用连接初始化、逐文件处理、
BM25 重建、索引状态标记和撤回收尾。目录入口要求向量后端可用；增量/指定文件
保留非严格模式的 lexical-only 行为，产物标记为 `partial`，且不加载 embedding 模型。
增量 `strict=True` 遇到后端/解析/入库失败即抛错；集合冲突始终报错，不作离线降级。
文档目录必须与 Data Persistence 的实际写入目录一致，不一致时在任何后端写入前报错。
BM25 输出显式使用 `BM25_INDEX_PATH`；未设置时写入所选文档目录的父目录，
不再读取检索模块导入时冻结的全局默认目录。

原 `structured_ingestion.py` 已删除，职责拆分为：
`ingestion.preparation` 的共享文档准备；`ingestion.publication` 的企业投影发布；
`ingestion.uploads` 的上传任务状态；`files.evidence` 的持久化快照/证据适配；
`indexing.vectors` 的共同向量写入；`indexing.worker` 的进程入口。
上传与批处理仍共享准备和向量处理，不按个人/企业来源复制处理算法。
旧平铺模块已迁移，仓库内调用均使用上述新路径，不保留同名转发文件。

从 `data-pipeline/` 目录执行：

```bash
python -m pipeline.entrypoints.process <folder>
python -m pipeline.entrypoints.auto_process --force --strict
python -m pipeline.entrypoints.process_specific_files <file1> <file2>
```

重建必须遵循隔离运行路径/集合的既有约定，不能用测试目录替换原索引。
独立向量进程使用 `python -m pipeline.indexing.worker` 的内部 stdin 协议，
不作为用户文件导入命令。

## 解析、切块和索引

2026-10-15 模块归属整理：章节标识、元数据规范化与导航候选选择归入
`pipeline.documents.sections`；Confluence 的 Windows HTTPS 兼容实现归入
`pipeline.confluence.transport`。文件配置/接口模型由 Data Persistence 提供。
独立视觉模型的加载、推理、子进程与图片区域分析入口已移除；不再使用
`LOCAL_VISION_*`、`ATTACHMENT_VISION_*` 或 `GPU_LEASE_PATH` 配置。
图片文字/表格 OCR 保留，Fast 原图理解仍由用户配置的多模态答案模型在同一次回答中完成。

2026-10-15：上传与批处理共用 `pipeline.files.parsing.parse_document(path)` / `parsers.registry.parse_file(path)`。
`parse_context(path, source_id)` 额外返回 `context/items/documents`，不执行分块或入库。
统一注册表按需加载解析器，补齐 TXT/CSV/JSON/XLS/PPT 与图片 OCR；常用 PDF/DOCX/PPTX/XLSX
直接复用原解析器，DOCX/PPTX 图片 OCR 也归入 Pipeline。HTML 只解析本地静态内容，不获取远程资源。
上传由 Toolset 薄适配器调用，Data Persistence 保存结构化快照并排队。企业批处理与个人库
统一使用 `pipeline.ingestion.preparation.prepare_document` 完成切块和章节构建，使用
`replace_document_vectors` 完成语义 embedding、显示文本与完整 provenance 的向量写入。
个人库从持久化快照恢复后调用同一处理入口；仅版本发布、存储目标与访问范围保留来源适配。
删除重复的 `private_ingestion.py` 和 `private_library.py`；配置归 Data Persistence，
索引版本发布归存储适配，候选融合归检索。不再保留私有向量适配器与独立 worker 文件。
企业与个人库通过 `index_document_vectors` 调用同一写入实现；Windows 在需要加载模型时
通过 `python -m pipeline.indexing.worker` 执行公共子进程，显式传入 Document、集合及连接目标。
`private_retrieval.py`、`private_tools.py`、`private_vectors.py` 和 `private_vector_worker.py` 已删除；
附件检索与个人库检索分别归现有 `tool_layer.attachment_tools`、`tool_layer.search_library_tool`，
工具进程内直接调用，不再经过模拟 HTTP 路径的分发层。
存储层 `get_file_vector_store()` 只选择隔离集合并复用公共 `MilvusStore`，不缓存授权或召回结果。
`MILVUS_CONNECT_RETRY_SECONDS` 默认 30 秒，统一控制连接失败后的退避；
`VECTOR_PROCESS_TIMEOUT_SECONDS` 默认 120 秒，统一控制向量子进程超时，兼容旧
`ATTACHMENT_VECTOR_PROCESS_TIMEOUT_SECONDS`。旧 `ATTACHMENT_VECTOR_CHILD` 和
`ATTACHMENT_VECTOR_RETRY_SECONDS` 不再使用。
个人库与企业库保留独立集合，owner/知识库/活动版本过滤不变；临时附件不另建向量索引。
私有集合现在也要求主管线的 provenance schema，不兼容时在删除旧向量前拒绝写入；
旧集合需先迁移至具备该 schema 的隔离集合，不能直接覆盖原索引。
上下文保留原始表格和 locator；PDF 坐标在上传 DTO 中转换为预览使用的相对坐标。

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

`pipeline.ingestion.preparation.prepare_ingestion_chunks()` 是共享切块入口。
全量 `process_folder()`、增量 `auto_process_raws()` 和定向 `process_specific_files()`
通过 `ingestion.batch.run_batch()` 与 `ingestion.publication.index_document()`
复用 Evidence/Section 双集合写入与 JSON 保存顺序。

每个 Chunk 同时保留 `index_text` 与 `markdown_text`；向量和 BM25 使用语义文本，
模型上下文及展示保留 Markdown。`text` 保持展示文本的兼容语义；旧 JSON 自动从
`text` 补齐新字段。结构化表格按上文 2026-10-16 规则生成有界表格/行组，不重复整表。
Wiki 理解仍要求精确 Evidence span；本次没有验证新表格分组对离线 Wiki 构建的全部覆盖，
不得把行组冒充整表。在线 Wiki 导航仍受既有 lineage 隔离约束，没有开启导航授权。

历史方案（2026-10-14，已由上文 2026-10-16 分组及 Reader 契约替代）：行级 `index_text` 保留列名与单元格值的对应关系，
`text` / `markdown_text` 引用完整原表，避免派生行标签无法在 Reader 正文定位。
空行不生成行级片段。无边框 PDF 仅在数字列对齐时接受 PyMuPDF text-grid 候选；
等行数数字单元格可以拆成多条指标行，复合表头仅按真实合并单元格坐标补齐。
这些改动需要用主管线重建 Evidence、Section 和 BM25，不能仅更新 JSON。

中文 hybrid 检索的 BM25 RRF 权重为 2，其他查询为 1，向量仍参与融合。
文档名匹配只收窄调用方已有授权列表：复合文件名要求公司、年份等全部字面组件
出现，中文部分标题要求至少四个连续字；不会扩大来源权限。
目录导航编号（如 `04 API Reference` 的 `04`）可以省略；来源年份和日期仍参与匹配。

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

## OCR 与解析依赖

Python 依赖统一在根 `requirements.txt` 维护，包含 Camelot/GMFT 表格解析和
PaddleOCR/PaddlePaddle 扫描件解析依赖。使用 `python -m pip install -r requirements.txt`
统一安装，不再单独维护表格 PDF/OCR 依赖文件。
通用正文 OCR 使用 PyMuPDF 的 Tesseract 后端，需要本机 Tesseract 和语言数据；
不自动安装语言包或模型。缺后端/语言或执行失败会记录诊断，并保留可读取的原生文字。

| 设置 | 用途 |
| --- | --- |
| `PDF_OCR_LANGUAGES` | 默认 `chi_sim+eng`；按已安装语言有界降级 |
| `PDF_OCR_DPI` | 72–600，默认 300 |
| `AI_QA_DATA_DIR` | raw 文件及其他持久化数据根目录；未指定文档目录时使用其 documents 子目录 |
| `BM25_INDEX_PATH` | BM25 索引路径，可在数据根目录外 |
| `MILVUS_COLLECTION` | 企业 Evidence 集合 |
| `SECTION_MILVUS_COLLECTION` | 独立 Section 集合，默认 `document_sections_bgem3` |

企业批处理与私有上传共用结构化解析、切块和向量写入；私有资料保留独立存储和权限。
上传身份、有效期和证据校验仍以当前访问契约为准。

## 维护工具

所有运行数据、源文件、模型和真实验收产物都应位于 checkout 外。
`RESEARCH_DOCUMENTS_DIR` 可单独指定权威文档目录；公共持久化、处理管线、检索和来源校验均读取此目录。未配置时使用 `AI_QA_DATA_DIR/documents`。切换文档索引无需移动聊天、附件等数据库。
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
## 完整 Confluence 页面与附件镜像（2026-10-14）

`confluence_pull.py --space-key RAG` 导出完整页面目录；它不下载附件，也不更新问答索引。
在成功的全量页面导出之后，运行 `confluence_attachments.py --space-root <raws/confluence/RAG>
--env-file <ignored credentials>`，枚举每页当前附件、分页下载原文件，并保存
`attachments-manifest.json` 和 `<attachment>.meta.json`。页面与附件分别计数，附件不代替父页面。
下载重定向只允许 HTTPS，跨站媒体请求不携带源站凭据。

随后仍使用原有 `pipeline.entrypoints.auto_process.auto_process_raws(force=True, strict=True)` 执行
原生 parser → structured chunker → 实际 embedding → Evidence/Section → JSON → BM25。
全量替换需要先将旧正文、raw 和 BM25 移出活动目录，再用新集合运行；不要混扫历史 `.doc` 导出。
调用方必须将 `AI_QA_DATA_DIR`、`RESEARCH_DOCUMENTS_DIR`、`BM25_INDEX_PATH`、
`MILVUS_COLLECTION` 和 `SECTION_MILVUS_COLLECTION` 配置到同一批数据。

来源 ID 使用 space + page ID；附件使用 space + attachment ID，父页面 ID 只用于来源归属与原生权限。
增量检测比较来源版本/hash/更新时间，而不是将 stable source ID 与文件路径 ID 混用。
成功的完整附件 manifest 可撤回已不再可见的附件，即使父页面仍然存在；不完整枚举不能作为撤回依据。
XLSX 表格边界包含保留的合并单元格完整行列跨度，避免只有合并起点非空时越界。
Milvus 标题等检索标签按 UTF-8 字节上限保存；完整标题和正文继续保存在 JSON，
不对证据正文做截断。续跑将重新处理尚未完成全局 BM25 发布的 `export_ready`/`partial` 投影。

当前原生注册解析器不接受单独 PNG 或 JSON 文件：这些文件仍完整下载到本地，
但不能将其下载成功计为正文解析或向量入库成功。需要分别报告源文件覆盖、可解析文档、
无正文/不支持的附件、投影 ID/version/hash、实际向量及 BM25 数量，以及目录权限登记结果。
