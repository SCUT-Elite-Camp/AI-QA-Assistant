# agent-layer

`agent-layer` 是 AI 智能问答项目的 Agent 层。当前 CP2 版本在 CP1 单轮 RAG
链路上增加了受信任的持久记忆上下文、`QueryPlan` 公共输入契约和有界多轮工具调用循环，
并继续通过 Tool Layer 与 OpenAI-compatible LLM 接口完成跨层集成。

## CP2 已实现范围

2026-10-15 已拆分为独立的 [FastPipeline](agent/chat/fast.py) 与
[ThinkingPipeline](agent/chat/thinking.py)，详见[模式契约](docs/chat_mode_contract.md)。
Fast 用原问题直接检索、程序固定调用工具，再进行一次生成；不改写、不扩展、不修复，
图片放入最终同一次模型请求。Thinking 负责规划、有界工具循环、证据整理和固定 Thinking
模型生成。`auto` 兼容到 Thinking；两条链路不隐式互转，JSON/SSE 共用业务流程。

- `MemoryCoordinator` 在请求边界解析 Web/BFF 显式提供的受信任记忆上下文。
- Agent 不按 `session_id` 缓存、恢复或写回对话历史。
- `QueryIntent` / `QueryPlan` 严格 Pydantic 契约。
- 两种模式都仅根据可信请求来源、文件及可用上下文确定来源范围；不从问句猜授权。
- Agent Runner 动态读取工具 schema，支持连续多轮工具调用。
- 每次实际工具执行均计入请求预算；重复动作达到阈值后终止。
- 最终回答、主动澄清、无上下文、最大迭代、重复调用、工具错误和 LLM 错误终止。
- Fast 检索直接使用原问题；Thinking 首次发送原问题和工具列表，模型自行选择检索词。
- `trace_id` 贯穿 Chat、Runner 与检索工具。
- `ThinkingPipeline` 准备可信 Memory 与来源范围，进入唯一有预算的 Agent 循环。
  澄清、改写和策略选择均由 Prompt 驱动；独立意图分类器、路由器与完整性生成调用已删除。
  答案通过片段绑定后由本地 MiniCheck 核验；未通过则在同一预算内继续取证或重新生成。
- CP1 Web `ChatResponse` 字段保持不变。
- 手动启动、与 Chat 隔离的 Local Deep Research API。
- SQLite 持久化 Job／Manifest／Plan／Approval／Evidence／Claim／Report，
  由低频 Durable Dispatcher 调度和恢复。
- Research 仅使用主 Agent 规划、人工修改/批准、并行子 Agent 探索、独立 Reviewer 和新修订 Agent 的 harness；主 Agent 执行时只协调、汇总及最终放行，不调用探索工具。旧运行图及兜底已删除。
- 证据链仍为 Search → Observation → Original Read → Evidence →
  Finding → Draft → Review/Repair → 主 Agent 放行；不再复制生成 Claims 或运行旧规则核验。
- Chat 与 Local Deep Research 统一输出 `{doc_id}_chunk_{index}` 稳定定位符；
  结构化文档按命中 chunk 精确读取原文，无 chunks 时才回退到行号定位。
- 支持资料充分的 `complete` 与资料不足或冲突的 `degraded` 结果。
- 普通 Chat 的企业、个人库、附件及混合来源门禁，当前授权/版本/hash 校验与完整来源依赖。
- Research 创建者身份、原生 Confluence 权限、共享企业 hybrid 检索及逐模型调用授权复核。
- 请求级 ContextVar 状态与并行检索授权传播，避免诊断/Memory 决策跨用户串用。

跨层契约见[架构](../docs/access-evidence/access-evidence-architecture.md)与[接入说明](../docs/access-evidence/access-evidence-integration.md)，真实结果见[整合报告](../docs/testing/integration/pr63-integration-acceptance.md)。Research 当前只支持企业来源；Wiki 导航因自身 lineage 不完备暂被隔离。

两种模式的标题都使用问题截取，不产生额外模型调用。Fast 本轮不追加后台 Memory 压缩。
Thinking 的所有控制、答案生成、失败尝试共用一个模型调用/工具/上下文/时间预算。

Fast 有证据问答的正文经过确定性引用校验后释放，不追加生成修复；失败状态为
`QUALITY_VALIDATION_FAILED`。展示引用仍指向当前原文，表格列名和值的语义对应
只从同一原表取得。详见[流式接入契约](../docs/access-evidence/access-evidence-integration.md)。

Fast 图片输入要求配置具有多模态能力的 `ANSWER_FAST_MODEL` 并显式开启
`FAST_MODEL_SUPPORTS_IMAGES=true`（默认 false）；不支持时返回 `unsupported`。
`FAST_CONTEXT_MAX_CHARS` 默认 12000。图片工具只读取已有解析/OCR及原图，
不调用独立视觉模型。Thinking 的统一预算及 MiniCheck 失败续答详见[模式契约](docs/chat_mode_contract.md)。

共享契约：

- [`QueryPlan / SourceIntent`](agent/schemas/query_plan.py)

2026-10-19 新增独立的[断言核验输入构造](docs/verification_context.md)：
从有效绑定和同一批 Evidence 构造保留结构、原文位置及 lineage 的输入，超预算明确标记需复核。
离线入口可用 `--prepare-only` 检查；Thinking 已将该构造器接入在线 MiniCheck，Fast 仍仅校验绑定。


## 开发准则

Agent 层开发以 [`docs/development_guide.md`](docs/development_guide.md) 为公共协作准则，覆盖分支结构、日常开发流程、PR 合并、Commit 命名和团队目录边界。

## Q1 范围（历史验收范围）

以下清单记录早期 Q1 的验收范围，不代表当前运行时的模块清单。

- FastAPI 服务入口
- `GET /health`
- `GET /ready` 检索冷启动就绪状态
- `POST /api/chat`
- ChatRequest / ChatResponse / Citation 接口契约
- Mock Retrieval
- Context Assembler
- Prompt Builder V1
- Mock LLM
- Tool Layer SearchTool 适配
- Mock / real 模式切换
- 低相关和空检索兜底
- 幻觉抑制 Prompt
- answer 与 citations 一致性检查
- Web CORS
- SSE 演示接口
- Demo 问题集和 Week 4 验收脚本
- Answer Formatter
- trace_id、基础 logger、状态码和 pytest

## 当前不做内容

- 不连接真实 HSBC 系统
- 不硬编码或提交真实密钥；服务从私有配置读取授权凭据
- 不接未经授权的客户/员工业务数据；授权的真实项目 Confluence 与本地 ACL 可用于验收
- 不在 Agent 层直接连接 Milvus、BM25 或 embedding API；真实检索通过 Tool Layer 接口接入
- 不自动把普通 Chat 升级为 Research，不使用匿名检索兜底
- 进程内短期会话记忆仍不跨 worker 共享；BFF 的持久历史、Snapshot 是独立机制

## 目录结构

```text
agent-layer/
├── app.py
├── agent/
│   ├── api/
│   ├── service/
│   ├── formatter/
│   ├── schemas/
│   ├── prompt/
│   ├── llm/
│   ├── retrieval/
│   ├── trace/
│   ├── logger/
│   ├── memory/
│   ├── runtime/
│   ├── config/
│   ├── errors/
│   └── streaming/
├── tests/
├── docs/
└── eval/
```

## 运行方式

```bash
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

## 测试方式

```bash
python -m pytest
```

真实边界和 Research 产品验收入口分别为 `python -m eval.integration_boundary_acceptance`
与 `python -m eval.research_product_acceptance`；先按[运行手册](../docs/access-evidence/access-evidence-runbook.md)
配置隔离数据路径、认证、模型与检索依赖。

2026-10-15 已删除旧 `mock/` 与 `scripts/` 目录，包括 CP1 样例、分层联调与阶段演示脚本、
重复测试包装和旧 G1/G2 评测包装。当前业务回归测试自行创建最小临时资料，覆盖计划来源限制、
资料冲突、报告与崩溃恢复；仅验证历史样例文件完整性的测试已删除。
历史交付文档中的旧目录和命令只供追溯，不再作为当前执行入口。

## API 示例

```bash
curl -X POST "http://localhost:8000/api/chat" \
  -H "Authorization: Bearer <AGENT_API_KEY>" \
  -H "X-User-ID: <enabled-and-native-bound-user>" \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"项目 Q1 阶段需要完成哪些功能？\",\"user_id\":\"<enabled-and-native-bound-user>\",\"stream\":false,\"retrieval_mode\":\"hybrid\"}"
```

响应包含既有答案/Citation 字段和来源依赖证明；以下仅展示结构，不是可用于验收的固定答案：

```json
{
  "trace_id": "trace-xxxxxxxx",
  "status": "success",
  "answer": "<根据当前已核验原文生成的回答> [1]",
  "message": "",
  "citations": [{"citation_id": 1, "doc_id": "example-doc", "chunk_id": "example-doc_chunk_0", "evidence_ref": "example-ref", "content_hash": "<body-sha256>"}],
  "evidence_provenance": {"schema_version": "evidence.provenance.v1", "complete": true, "dependencies": [{"source_type": "knowledge", "doc_id": "example-doc", "version": "1", "content_hash": "<body-sha256>"}]}
}
```

## 测试隔离说明

- pytest 会替换 LLM 与 SearchTool，测试不依赖外部模型、Milvus 或 embedding 包。
- 运行服务时默认使用 Tool Layer 的 `SearchTool` 和 OpenAI-compatible `LLMClient`。
- 测试数据由测试代码在临时目录创建，旧 CP1 请求与答案样例已删除。

## 运行配置

```env
LLM_API_KEY=
LLM_API_BASE=http://127.0.0.1:11434/v1
LLM_MODEL=llama3.1
ANSWER_FAST_MODEL=
ANSWER_FAST_MODEL_THINKING=false
THINKING_MAX_MODEL_CALLS=10
THINKING_MAX_TOOL_CALLS=8
THINKING_CONTEXT_MAX_CHARS=30000
THINKING_MAX_RESERVED_TOKENS=150000
THINKING_MAX_VERIFICATIONS=48
THINKING_TIMEOUT_SECONDS=180
MAX_REPEATED_TOOL_CALLS=2
MINICHECK_MODEL_PATH=data-persistence/models/minicheck
MINICHECK_CPU_THREADS=4

# 接口共享密钥（必配）：Web 可信端调用 /api/* 业务接口时携带
# `Authorization: Bearer <AGENT_API_KEY>`。未配置时业务接口返回 503，
# 防止外部直连 agent 端口伪造 user_id 绕过权限隔离。
AGENT_API_KEY=

# 权限查询异常策略（默认 false = fail-closed，拒绝全部文档；故障时避免权限全开）
PERMISSION_FAIL_OPEN=false
```

`top_k=5` 和 `retrieval_mode=hybrid` 是 ChatRequest 的请求模型默认值，不是环境变量。
独立分类、改写、澄清及完整性模块的旧配置已移除，不再影响 Thinking。

### 接口认证说明

Agent 服务仅接受 Web 可信端的调用（内网单向可信链路）。所有 `/api/*` 业务接口
（`/api/chat`、`/api/chat/stream`、`/api/tools`、
`/api/topics/summarize`）都要求携带共享密钥：

```bash
curl -X POST "http://localhost:8000/api/chat" \
  -H "Authorization: Bearer <AGENT_API_KEY>" \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"...\",\"retrieval_mode\":\"hybrid\",\"user_id\":\"...\"}"
```

- `AGENT_API_KEY` 未配置：业务接口返回 `503`（拒绝服务）。
- 缺少/错误的密钥：返回 `401`。
- `GET /health` 保持匿名（供探活）。
- 校验使用 `secrets.compare_digest` 恒定时间比较，防时序攻击。

`AGENT_API_KEY` 需与 Web 层 `frontend/.env` 中配置的值保持一致（Web 转发 session 注入的
`user_id` 并附带相同的 Bearer 密钥）。

本地 Ollama 启动后，可通过兼容 OpenAI Chat Completions 的
`/v1/chat/completions` 接口接入 `llama3.1`，通常不需要配置
`LLM_API_KEY`。检索始终从 Tool Layer 的注册表加载，Agent 层不直连检索存储。

CP2 工具注册表实现见 [`registry.py`](agent/tools/registry.py)，当前接口见 `docs/API_CONTRACT.md`。

Thinking 当前实现与预算见 [`runner.py`](agent/runtime/runner.py) 和[模式契约](docs/chat_mode_contract.md)。

Thinking 的澄清与策略由 [`thinking_prompt.py`](agent/chat/thinking_prompt.py) 定义。

CP2 `QueryIntent`、`QueryPlan` 字段契约见 [`query_plan.py`](agent/schemas/query_plan.py)。

CP2 Chat-only L0/L1/L2 路由边界见
[`docs/cp2/chat_route_policy.md`](docs/cp2/chat_route_policy.md)。

手动启动 Local Research 的 `research.v1` 契约和 Planner Fixture 见
[`docs/cp2/research_contract_v1.md`](docs/cp2/research_contract_v1.md)。

CP2 Research Progress/Event 后端与前后端正式接入交付见
[`docs/cp2/week_research_progress_member_a_delivery.md`](docs/cp2/week_research_progress_member_a_delivery.md)。

QueryPlan 只保留公共 DTO；不再执行独立意图分类或按意图选择链路。

## 分工建议

成员 A：Agent 业务主流程负责人，也就是 xdj

- `agent/api/`
- `agent/service/`
- `agent/prompt/`
- `agent/llm/`
- `agent/formatter/`
- `agent/schemas/chat.py`
- `docs/interface_contract.md`

成员 B：Agent 基础设施负责人，也就是 lhf

- `agent/retrieval/`
- `agent/logger/`
- `agent/trace/`
- `agent/config/`
- `agent/errors/`
- `tests/`
- `agent/schemas/retrieval.py`

共同负责：

- `agent/schemas/common.py`
- Web 联调
- Bug 修复
- Demo 问题集验证
- `docs/cp1/integration_record.md`

## Git 协作建议

- `main`：稳定版本
- `dev`：日常开发版本
- `feature/agent-core`：xdj 开发 Agent 主流程
- `feature/agent-infra`：lhf 开发基础设施和检索适配
- `feature/integration`：第 3-4 周联调分支

## Week 3 质量控制

真实 Confluence 的 Agent 独立产品验收集、复现命令与范围说明见
[产品验收集 v1](docs/cp2/product_acceptance.md)。它区分运行成功、答案质量与人工验收，
不替代 dev 的全项目集成验收。

- 空输入直接返回 `invalid_query`。
- 检索为空或低于 `MIN_RETRIEVAL_SCORE` 时返回 `no_relevant_context`，不调用 LLM。
- 检索异常返回 `retrieval_error`。
- LLM 异常或空输出返回 `llm_error`。
- Prompt 明确要求只基于检索上下文回答，不得编造。
- 成功响应会规范化 answer 中的引用编号，避免 `[9]` 这类无效 citation。

## Week 4 Web 联调

- 普通问答接口：`POST /api/chat`。
- SSE 演示接口：`POST /api/chat/stream`。
- Web 联调说明见 `docs/cp1/web_integration_guide.md`。
- 最终交接说明见 `docs/cp1/final_handoff.md`。

Research now reserves reasoning and visible-output tokens separately, and stages truncated
reports into sections before the existing evidence gates. Configuration and limitations:
[Research generation budgets](docs/research_generation_budget.md).

生产企业任务默认使用 [Research coordinator architecture](docs/research_team_architecture.md)：
计划公开文件目录、任务分工和验收目标，人工修改后须重新批准；默认 3 个并发探索 Agent、
最多 2 轮独立修订。Reviewer 按报告 revision/hash 核实引用原文，主 Agent 最后确认后才发布。
所有执行角色共享持久化 Token/工具预算，恢复不会重置预算。此链路的确定性回归通过
不代表已经完成真实 Groq、Milvus 与 Confluence 权限验收。

本地开发 Research 设置 `RESEARCH_DEVELOPMENT_MODE=true`、`HOST=127.0.0.1`：
已登录且启用的用户可访问完整 Research 文件目录，无需逐文件或原生授权；任务归属、
来源版本/hash 和复审放行仍检查。生产配置保持该开关为 false。
旧 legacy 任务保留已保存结果，但不再执行或恢复；需要新建并批准 harness 计划。
