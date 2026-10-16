# 隔离联调运行与复现

2026-10-15 上传运行变更：仅启动 Web 与 Agent；附件 HTTP API 已合入 Agent 的
`/private-files`，不再启动独立的 8200/8219 进程，`ATTACHMENT_SERVICE_URL` 已废弃。
Web 设置正确的 `AGENT_BASE_URL`，Web 与 Agent 使用匹配的 `ATTACHMENT_INTERNAL_SECRET`。Python 内部工具直接调用 Pipeline/存储，不通过同步 HTTP 回调 Agent 自身。
Agent 设置 `ATTACHMENTS_ENABLED=true`、`PERSONAL_LIBRARY_ENABLED=true`、
`ATTACHMENT_VECTOR_INDEX_ENABLED=true`、原 `ATTACHMENT_ENCRYPTION_KEY/ATTACHMENT_DATA_DIR`。
保留原存储目录、key 与私有集合，不清理旧数据库或索引。Schema 自动增加解析快照表；
旧版本仍可读取，新上传复用统一解析，新入库自动排队。旧代码启动的独立附件进程
应在迁移时由操作者停止，避免不同代码同时消费同一队列。

2026-10-12 表格解析整合补充：新企业 Evidence 集合增加结构化溯源字段；已有集合可继续读取，但新结构化写入在替换前检查 schema。向量与 BM25 使用 `index_text`，展示及上下文保留 `markdown_text`。迁移使用全新数据目录、Evidence/Section 集合并保持实际 embedding 维度一致；本次合并没有执行重建或切换既有索引。详见[现行管线契约](../data-pipeline/DATA_PIPELINE.md)及[本轮验证记录](../data-pipeline/table-processing-integration-20261012.md)。

更新：2026-10-09。使用独立数据库、正文投影、BM25、Milvus 项目和集合，不覆盖原仓库索引/会话库。

## 配置

Deep Research 网页默认覆盖当前账号可读的全部 Confluence 文档，无需选源。
计划审批仍绑定本次 Manifest；文档更新后应新建研究。提示和状态文字为英文。
网页使用 `/api/research/jobs/{id}/snapshot` 合并轮询 Job/Progress/Events，
每次请求仍实时复核权限和源版本，完成后等待 5 秒再次请求。

基础配置统一以 `agent/.env.example`、`frontend/.env.example` 为准。Agent 的内部 token、
附件 HMAC secret、Fernet encryption key 和 Confluence 配置示例都在 `agent/.env.example`，
复制为被忽略的 `agent/.env` 后填写；不再维护单独的联调或来源权限配置模板。

已有的 `agent/.source-access.env.local` 可继续保留，通过 `CONFLUENCE_AUTH_ENV_FILE`
指定其绝对路径读取，包含 `CONFLUENCE_BASE/EMAIL/TOKEN/ACCOUNT_BINDINGS`。
这些变量也可直接在 `agent/.env` 配置，环境变量优先于凭据文件。
历史联调的 `-BaseEnvironment` 私有 PowerShell 配置和已存在的
`.integration-runtime.env.local` 均不会因模板合并而自动迁移或删除。

Agent 与 Web 共享内部密钥并读取同一份 Web SQLite。私有配置已忽略，禁止提交实际值。源站账号 ID 必须来自已核实账号；不要将一个绑定复制到全部本地用户。

| 配置 | 所在进程/作用 |
| --- | --- |
| `SOURCE_ACCESS_MODE=native` | Agent，Confluence 原生有效权限检查；不要设为离线授权模式代替验收 |
| `CONFLUENCE_AUTH_ENV_FILE` | Agent，指定私有邮箱/token/绑定配置路径 |
| `CONFLUENCE_HTTP_TRANSPORT=curl` | 可选 Windows 本地兼容模式：Confluence 导出与原生 read 检查使用系统 `curl.exe` 的 TLS；凭据经标准输入传递，仍禁止重定向 |
| `CONFLUENCE_BASE/EMAIL/TOKEN/ACCOUNT_BINDINGS` | 源站与本地 user → `{site,account_id}` 映射；环境变量优先于文件 |
| `AGENT_API_KEY`、`AGENT_INTERNAL_TOKEN` | Agent/Web，公共业务 Bearer 与内部请求 token |
| `WEB_SQLITE_PATH`、`TURSO_DATABASE_URL` | Agent/Web 必须指向同一权限/会话库 |
| `RESEARCH_DOCUMENTS_DIR`、`AI_QA_DATA_DIR`、`BM25_INDEX_PATH` | 权威正文、数据存储与词法索引隔离路径 |
| `RESEARCH_DATABASE_PATH`、`RESEARCH_CHECKPOINT_PATH` | Research Job 与 checkpoint 隔离存储 |
| `TOPICS_DATA_DIR` | Web/Agent 共享的 Topic 文件目录；两端必须相同 |
| `ATTACHMENT_DATA_DIR`、`AGENT_BASE_URL`、`ATTACHMENT_INTERNAL_SECRET`、`ATTACHMENT_ENCRYPTION_KEY` | Agent 托管私有文件 API；持久化路径与认证/加密 |
| `ATTACHMENTS_ENABLED`、`PERSONAL_LIBRARY_ENABLED`、`ATTACHMENT_VECTOR_INDEX_ENABLED` | 联调时均 true，私人向量集合不得与企业集合相同 |
| `LOCAL_EMBEDDING_MODEL_DIM`、`MILVUS_COLLECTION`、`ATTACHMENT_MILVUS_COLLECTION` | 企业、私有查询向量与各自 collection schema 的维度必须一致；本轮 384 |
| `MILVUS_HOST`、`MILVUS_PORT`、`SECTION_MILVUS_COLLECTION` | 当前向量服务与导航集合；隔离恢复应指向独立服务和新集合，保留原有 volumes |
| `MILVUS_LOAD_TIMEOUT_SECONDS` | 集合加载等待上限，默认 10 秒；无效、非正或非有限值回退到 10 秒，避免请求无限阻塞 |
| `AI_QA_BUILD_DIR` | Vite 输出目录覆盖，不把大型构建放进空间不足的盘 |
| `SESSION_COOKIE_SECURE`、`ALLOW_DEV_LOGIN` | 仅回环 HTTP 联调可用 false/true；生产应 HTTPS、secure Cookie，禁用 dev-login |
| `AI_QA_ACCEPTANCE_VOLUME_ROOT` | 独立 Compose volume 根目录；脚本不会替用户清空旧 volume |

## Windows 隔离启动

先按上表配置 checkout 外的独立 runtime、正文、权限库、Research DB/checkpoint、附件目录及
企业/私有集合，并设置真实模型与 embedding 配置。Web 的 `TURSO_DATABASE_URL` 和
Agent 的 `WEB_SQLITE_PATH` 必须指向同一份已迁移数据库。下面的 `$python` 是虚拟环境解释器
的绝对路径；在不同终端继承同一份服务端环境配置。

```powershell
# Repository root: the Agent also hosts private file APIs and Pipeline workers.
& $python -m app

# Another terminal, from frontend/: migrate the isolated Web database and start Web.
pnpm run db:migrate
pnpm run dev
```

Windows 生产式联调可使用 `pnpm build` 后运行其生成的 Node server；
`AI_QA_BUILD_DIR` 可以将输出移到 checkout 外。不要再启动独立附件进程。
隔离 Compose 仍可使用 `AI_QA_ACCEPTANCE_VOLUME_ROOT` 和独立项目名，保留原 volumes、
BM25 与集合。实际模型/源站配置和冻结 fixture 不在仓库中，不能用 mock 代替真实验收。

## 三类来源与真实质量验收

先确认 `/health`、`/ready`、Milvus health。基础配置的模型调用会产生实际费用；不使用 mock parser/embedding/model/ACL 冒充端到端。按 2026-10-12 产品要求，附件服务已移除病毒扫描依赖，上传只执行格式/大小校验、解析和上下文构建。

```powershell
Push-Location agent
& $python -m eval.integration_boundary_acceptance --web http://127.0.0.1:3019 `
  --runtime $runtime --output 'C:/aiqa-acceptance/boundary-new-run'
& $python -m eval.integration_boundary_acceptance --web http://127.0.0.1:3019 `
  --runtime $runtime --output 'C:/aiqa-acceptance/lifecycle-new-run' --lifecycle-only

# Set AGENT_API_KEY and use a fresh output directory; grading follows the Codex per-case policy.
& $python -m eval.research_product_acceptance --base-url http://127.0.0.1:8109 `
  --user-id accept-alice --other-user-id accept-bob --documents $sources --metadata $metadata `
  --holdout-file "$runtime/frozen_holdouts.json" --output 'C:/aiqa-acceptance/quality-new-run' `
  --permission-db "$runtime/permissions.db" --forbidden-doc-id '<fixture.json 中的 forbidden_doc_id>' `
  --revocation-doc-id '<fixture.json 中的 revocation_doc_id>' --server-log "$runtime/agent.log"
Pop-Location
```

权限负例必须是当前身份 **ACL 拒绝** 的存在文档，不能使用题目里的“不得引用但用户有权读”的文档替代。CLI 因此要求显式 `--forbidden-doc-id`。撤权测试仅可修改带 `research_acceptance_fixture.marker=isolated` 的临时库，finally 恢复授权，不能对原生产库运行。

G1 为普通 Chat；G2 为创建、规划、批准、执行、读取报告的完整 Research。使用相同真实冻结来源及 hybrid 检索；7 道参与过修复的题是回归集，3 道在生成前冻结的新题是小型留出集。它们不证明广泛泛化能力。所有失败、评分争议、未评分与重跑都须保留，不能择优覆盖同一目录。

## 排查

| 表象 | 先检查 | 不应做的事 |
| --- | --- | --- |
| 源站 403 / 目录为空 | 用户启用状态、本地 ACL、站点/account ID 绑定、源站 read | 给所有用户继承服务账号权限 |
| 503 | native 网络/凭据、私有服务、Wiki 安全隔离 | 去掉权限过滤、换 BM25 宣称 hybrid 已通过 |
| 私有搜索 422 / 空结果 | 请求维度、实际 embedding 与 collection schema、活动版本/作用域 | 硬编码 1024、用跨 owner 文档补位 |
| Reader 404 / 409 | 消息 ID 的 URL 解码、证据绑定、当前角色、版本/hash | 按客户端 doc ID 直接读原文 |
| Docker 退出/磁盘满 | `docker info`、指定项目容器、volume 盘剩余空间 | `down -v`、删除原 collection、覆盖原 BM25 |
| 回答短缺但 HTTP 200 | 原文正确章节覆盖、实际 Citation、正文与机器评分 | 把任务完成等同质量通过 |

回滚先停写并备份；不反向执行 0015，不用旧代码解释新的 lineage 数据。故障恢复后先恢复原 fixture grant，再验证 Reader 和历史，最后跑质量。详细结果见[整合验收报告](../testing/integration/pr63-integration-acceptance.md)。

## 来源更新后的测试基准（2026-10-10）

历史 v1 预期不能直接用于已经修改的 Confluence 页面。先通过 `data-pipeline/confluence_pull.py --page-id ... --env-file <ignored path> --output-dir <isolated export>` 只读导出当前 XHTML/Markdown/metadata，再用现有 snapshot 校验、原生 parser/chunker 生成新投影。直接调用导出脚本时，将 `data-pipeline/` 与 `data-persistence/` 加入 `PYTHONPATH`，以加载解析、来源和存储接口。
`pipeline.entrypoints.auto_process` 的 raw 目录为 `AI_QA_DATA_DIR/raws`，文档目录使用 Data Persistence 的统一解析结果（默认 `AI_QA_DATA_DIR/documents`），`RESEARCH_DOCUMENTS_DIR` 必须与它保持一致；导出目标应放在 raw 目录的 `confluence` 下。切换当前索引时，Agent 的 `AI_QA_DATA_DIR`、`RESEARCH_DOCUMENTS_DIR`、`BM25_INDEX_PATH` 与 `MILVUS_COLLECTION` 必须同时指向同一批新投影。

为新投影建立独立 BM25 文件和全新 Milvus collection；不得删除或覆盖旧集合。使用同一实际 embedding，核对向量维度和实体数量。`AI_QA_DATA_DIR/documents` 与 `RESEARCH_DOCUMENTS_DIR` 必须是同一正文目录；Toolset 当前使用前者，Research 配置使用后者，单独改后者不能切换工具层资料。Web SQLite、Research DB/checkpoint、Topic 和附件路径仍必须在隔离区并由服务共享。

依据新源文本，在生成任何模型答案前创建独立版本的问题、检查项与 source hash/version。保留旧题、旧 manifest 和旧成绩；有重复 Goal ID 时同时以能力名称区分，空状态不从相邻行推断。仓库中的 `eval/deep_research_a/datasets/cases.en.current-20261009.v2.json` 是三个当前版本回归用例，不是未见留出集；正文和运行数据库仍位于 ignored/outside-checkout 路径。

结构化机器裁判对 Qwen 使用显式 `enable_thinking=false`，独立于业务回答的思考设置。保存实际请求选项、每次原始输出与验证结果；非法格式或明确理由/布尔矛盾仅重试一次，有效失败评分不重试、不翻转，异常仍作为未评分。重评现成答案必须记录原始记录路径和答案 hash，不覆盖原评分或重新生成回答来消除评分异常。
