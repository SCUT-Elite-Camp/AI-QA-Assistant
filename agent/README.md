# agent-layer

`agent-layer` 是 AI 智能问答项目 Q1 阶段的 Agent 层仓库，用于实现简化版单轮 RAG Agent。当前版本默认使用 Mock Retrieval 和 Mock LLM，也支持按配置接入 Tool Layer 检索和 OpenAI-compatible LLM Client。

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
- Answer Formatter
- trace_id、基础 logger、状态码和 pytest

## 不做内容

- 不实现复杂多步 Agent
- 不连接真实 HSBC 系统
- 不读取真实密钥
- 不接真实客户、员工、权限数据
- 默认不调用真实 LLM
- 默认不调用真实检索工具
- 不在 Agent 层直接连接 Milvus、BM25 或 embedding API；真实检索通过 Tool Layer 接口接入
- SSE / fetch stream 仅预留，不强制实现真实流式输出

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

## Mock 说明

- `agent/retrieval/mock_retrieval.py` 默认返回 3 条模拟文档块。
- `agent/llm/mock_llm.py` 返回带 `[1]` 引用编号的模拟答案。
- `mock/` 目录提供请求、检索结果和答案样例。
- `RetrievalAdapter` 默认使用 Mock；设置 `USE_MOCK_RETRIEVAL=false` 后会动态加载 `TOOL_LAYER_IMPORT` / `TOOL_LAYER_CLASS`，默认是 `tool_layer.SearchTool`。
- `LLMClient` 默认不启用；设置 `USE_MOCK_LLM=false` 后会使用兼容 OpenAI Chat Completions 的 HTTP 接口。

## 真实模式配置

```env
USE_MOCK_RETRIEVAL=false
DEFAULT_RETRIEVAL_MODE=hybrid
TOOL_LAYER_IMPORT=tool_layer
TOOL_LAYER_CLASS=SearchTool

USE_MOCK_LLM=false
LLM_API_KEY=
LLM_API_BASE=https://api.openai.com/v1
LLM_MODEL=gpt-3.5-turbo
```

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
- `docs/integration_record.md`

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
