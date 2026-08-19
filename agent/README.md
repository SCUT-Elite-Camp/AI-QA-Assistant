# agent-layer

`agent-layer` 是 AI 智能问答项目的 Agent 层。当前 CP2 版本在 CP1 单轮 RAG
链路上增加了会话短期记忆、`QueryPlan` 公共输入契约和有界多轮工具调用循环，
并继续通过 Tool Layer 与 OpenAI-compatible LLM 接口完成跨层集成。

## CP2 已实现范围

- `ConversationMemory` 稳定接口及线程安全的进程内实现。
- 基于 `session_id` 的上下文读取、写回、隔离、截断和清理。
- `QueryIntent` / `QueryPlan` 严格 Pydantic 契约。
- `SourceIntent` 在现有 QueryPlanner 调用内选择 Personal、Enterprise、会话附件或
  Web 多数据源，并以 shadow/canary/default 渐进启用；授权身份仍只来自可信请求上下文。
- Agent Runner 动态读取工具 schema，支持连续多轮工具调用。
- 最终回答、主动澄清、无上下文、最大迭代、重复调用、工具错误和 LLM 错误终止。
- 检索统一使用 `standalone_query`，保留 `original_query` 用于对话、记忆和审计。
- `trace_id` 贯穿 Chat、Runner 与检索工具。
- `AgentOrchestrator` 编排 Memory、Query Understanding、IntentPolicy、工具
  执行、Evidence Gate、纠偏检索和 Citation 校验。
- CP1 Web `ChatResponse` 字段保持不变。

共享契约：

- [`docs/cp2/query_plan_contract.md`](docs/cp2/query_plan_contract.md)
- [`docs/cp2/conversation_memory_contract.md`](docs/cp2/conversation_memory_contract.md)

## 开发准则

Agent 层开发以 [`docs/development_guide.md`](docs/development_guide.md) 为公共协作准则，覆盖分支结构、日常开发流程、PR 合并、Commit 命名和团队目录边界。

## Q1 范围

- FastAPI 服务入口
- `GET /health`
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
- 不读取真实密钥
- 不接真实客户、员工、权限数据
- 不在 Agent 层直接连接 Milvus、BM25 或 embedding API；真实检索通过 Tool Layer 接口接入
- SSE / fetch stream 仅预留，不强制实现真实流式输出
- 进程重启、多 worker 之间的记忆持久化与共享

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
├── mock/
├── tests/
├── docs/
└── scripts/
```

## 运行方式

```bash
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

## 测试方式

```bash
pytest
python scripts/check_contract.py
python scripts/run_week4_acceptance.py
```

## API 示例

```bash
curl -X POST "http://localhost:8000/api/chat" \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"项目 Q1 阶段需要完成哪些功能？\",\"stream\":false,\"retrieval_mode\":\"hybrid\"}"
```

成功响应示例：

```json
{
  "trace_id": "trace-xxxxxxxx",
  "status": "success",
  "answer": "Q1 阶段需要完成简化版单轮 RAG Agent，包括 /api/chat、Mock Retrieval、Prompt Builder、Mock LLM 和 Answer Formatter 等最小闭环能力。[1]",
  "message": "",
  "citations": []
}
```

## 测试隔离说明

- pytest 会替换 LLM 与 SearchTool，测试不依赖外部模型、Milvus 或 embedding 包。
- 运行服务时默认使用 Tool Layer 的 `SearchTool` 和 OpenAI-compatible `LLMClient`。
- `mock/` 目录仍保留 CP1 请求与答案样例。

## 运行配置

```env
DEFAULT_RETRIEVAL_MODE=hybrid
LLM_API_KEY=
LLM_API_BASE=http://127.0.0.1:11434/v1
LLM_MODEL=llama3.1
QUERY_UNDERSTANDING_ENABLED=true
QUERY_REWRITE_ENABLED=true
CLARIFICATION_ENABLED=true
MEMORY_ENABLED=true
MAX_MEMORY_MESSAGES=10
MAX_AGENT_ITERATIONS=5
MAX_REPEATED_TOOL_CALLS=2
```

本地 Ollama 启动后，可通过兼容 OpenAI Chat Completions 的
`/v1/chat/completions` 接口接入 `llama3.1`，通常不需要配置
`LLM_API_KEY`。检索始终从 Tool Layer 的注册表加载，Agent 层不直连检索存储。

CP2 工具注册表接口及 `/api/tools` 返回结构见
[`docs/cp2/tool_registry.md`](docs/cp2/tool_registry.md)。

CP2 查询重写接口、失败回退和推荐接入顺序见
[`docs/cp2/query_rewriter.md`](docs/cp2/query_rewriter.md)。

CP2 澄清判断场景、失败降级和推荐接入顺序见
[`docs/cp2/clarification.md`](docs/cp2/clarification.md)。

CP2 `QueryIntent`、`QueryPlan` 字段语义和双方消费约定见
[`docs/cp2/query_plan_contract.md`](docs/cp2/query_plan_contract.md)。

CP2 意图分类组件、失败回退和 QueryPlan 映射约定见
[`docs/cp2/intent_classifier.md`](docs/cp2/intent_classifier.md)。

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
- Demo 问题集见 `mock/demo_questions.json`。
- 最终交接说明见 `docs/cp1/final_handoff.md`。
