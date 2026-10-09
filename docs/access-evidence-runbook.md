# 隔离联调运行与复现

更新：2026-10-09。使用独立数据库、正文投影、BM25、Milvus 项目和集合，不覆盖原仓库索引/会话库。

## 配置

基础配置仍以 `agent/.env.example`、`frontend/.env.example`、`attachment-service/.env.example` 为准。Windows 联调脚本另读取：

1. `-BaseEnvironment` 指定的私有 PowerShell 配置脚本：设置真实 LLM、embedding 路径、Bearer、稳定 Session secret 等。
2. `agent/.integration-runtime.env.local`：按 `.integration-runtime.env.example` 填入内部 token、附件 HMAC secret、Fernet encryption key。
3. `agent/.source-access.env.local`：按 `.source-access.env.example` 填入 Confluence 站点、邮箱、token 和显式用户绑定。

三个服务共享内部密钥；Agent 与 Web 读同一份 Web SQLite。私有配置已忽略，禁止提交实际值。源站账号 ID 必须来自已核实账号；不要将一个绑定复制到全部本地用户。

| 配置 | 所在进程/作用 |
| --- | --- |
| `SOURCE_ACCESS_MODE=native` | Agent，Confluence 原生有效权限检查；不要设为离线授权模式代替验收 |
| `CONFLUENCE_AUTH_ENV_FILE` | Agent，指定私有邮箱/token/绑定配置路径 |
| `CONFLUENCE_BASE/EMAIL/TOKEN/ACCOUNT_BINDINGS` | 源站与本地 user → `{site,account_id}` 映射；环境变量优先于文件 |
| `AGENT_API_KEY`、`AGENT_INTERNAL_TOKEN` | Agent/Web，公共业务 Bearer 与内部请求 token |
| `WEB_SQLITE_PATH`、`TURSO_DATABASE_URL` | Agent/Web 必须指向同一权限/会话库 |
| `RESEARCH_DOCUMENTS_DIR`、`AI_QA_DATA_DIR`、`BM25_INDEX_PATH` | 权威正文、数据存储与词法索引隔离路径 |
| `RESEARCH_DATABASE_PATH`、`RESEARCH_CHECKPOINT_PATH` | Research Job 与 checkpoint 隔离存储 |
| `TOPICS_DATA_DIR` | Web Topic 文件隔离目录 |
| `ATTACHMENT_DATA_DIR`、`ATTACHMENT_SERVICE_URL`、`ATTACHMENT_INTERNAL_SECRET`、`ATTACHMENT_ENCRYPTION_KEY` | 私有解析服务、存储与认证/加密 |
| `ATTACHMENTS_ENABLED`、`PERSONAL_LIBRARY_ENABLED`、`ATTACHMENT_VECTOR_INDEX_ENABLED` | 联调时均 true，私人向量集合不得与企业集合相同 |
| `LOCAL_EMBEDDING_MODEL_DIM`、`MILVUS_COLLECTION`、`ATTACHMENT_MILVUS_COLLECTION` | 企业、私有查询向量与各自 collection schema 的维度必须一致；本轮 384 |
| `AI_QA_BUILD_DIR` | Vite 输出目录覆盖，不把大型构建放进空间不足的盘 |
| `SESSION_COOKIE_SECURE`、`ALLOW_DEV_LOGIN` | 仅回环 HTTP 联调可用 false/true；生产应 HTTPS、secure Cookie，禁用 dev-login |
| `AI_QA_ACCEPTANCE_VOLUME_ROOT` | 独立 Compose volume 根目录；脚本不会替用户清空旧 volume |

## Windows 隔离启动

以下命令从仓库根运行。`$runtime`、`$sources`、`$metadata`、`$python`、`$baseEnv` 应替换为本机明确的绝对路径；runtime 必须在 checkout 外并使用新空目录。需要真实冻结 JSON 文档和 Confluence metadata，仓库不提交用户私有源文件。

```powershell
$env:AI_QA_ACCEPTANCE_VOLUME_ROOT='C:/aiqa-acceptance/volumes'
docker compose -p aiqa-pr63-acceptance -f docker-compose.acceptance.yml up -d
Invoke-WebRequest http://127.0.0.1:9099/healthz

./scripts/Start-PR63Acceptance.ps1 -BaseEnvironment $baseEnv -Python $python `
  -Runtime $runtime -Sources $sources -Metadata $metadata -Prepare

Push-Location frontend
$env:AI_QA_BUILD_DIR='C:/aiqa-acceptance/web-build'
pnpm build
Pop-Location

./scripts/Start-PR63Acceptance.ps1 -BaseEnvironment $baseEnv -Python $python `
  -Runtime $runtime -Start -WebBuild $env:AI_QA_BUILD_DIR
```

Docker Engine 未启动时先开启 Docker Desktop 并等待 `docker info` 可用；脚本不会自动清理其他 Docker 项目。独立 Milvus 暴露回环 `19539/9099`；Agent `8109`、Attachment `8219`、Web `3019`。端口占用会直接失败，不杀现有服务。Windows 使用生产构建运行，避免 Nitro dev 在 junction 环境下的模块解析问题。

`-Prepare` 先执行完整 Drizzle migrations，再构建冻结投影/两路检索 fixture；已有 fixture 不重新初始化，向量中断只可使用 `-ResumeVectors`，且核对正文与 holdout 不变。`-WebOnly/-AgentOnly/-AttachmentOnly` 用于已停下的明确服务重启。

启动脚本是本机联调便利脚本，不是生产部署编排器，不自动重启崩溃进程；正式服务需专门的 supervisor。旧版 favorites JSON 导出可能落在 checkout 的已忽略 `frontend/data-persistence/`，不是当前 Favorites API 的权限权威，也不能作为 Memory 输入。

## 三类来源与真实质量验收

先确认 `/health`、`/ready`、Milvus health。基础配置的模型调用会产生实际费用；不使用 mock scanner/embedding/model/ACL 冒充端到端。

```powershell
Push-Location agent
& $python -m eval.integration_boundary_acceptance --web http://127.0.0.1:3019 `
  --runtime $runtime --output 'C:/aiqa-acceptance/boundary-new-run'
& $python -m eval.integration_boundary_acceptance --web http://127.0.0.1:3019 `
  --runtime $runtime --output 'C:/aiqa-acceptance/lifecycle-new-run' --lifecycle-only

# 先按基础配置设置 AGENT_API_KEY 与机器裁判 LLM_API_*；每次用新 output 目录。
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

回滚先停写并备份；不反向执行 0015，不用旧代码解释新的 lineage 数据。故障恢复后先恢复原 fixture grant，再验证 Reader 和历史，最后跑质量。详细结果见[整合验收报告](pr63-integration-acceptance.md)。
