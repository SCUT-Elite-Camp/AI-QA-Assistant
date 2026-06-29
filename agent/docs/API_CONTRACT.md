# API Contract

## POST /api/chat

Current stage: Week 3 single-turn RAG chain with configurable Mock / Tool Layer retrieval, configurable Mock / real LLM client, quality gates, hallucination suppression, and citation consistency checks.

The endpoint runs the minimal Agent Core flow:

```text
request validation -> ChatService -> RetrievalAdapter -> ContextAssembler -> PromptBuilder -> LLM -> AnswerFormatter -> JSON response
```

`stream` is reserved for future SSE or fetch streaming support. In the current implementation, requests with `stream: true` still return normal JSON.

## Request

```json
{
  "query": "项目 Q1 阶段需要完成哪些功能？",
  "session_id": "local-session-001",
  "top_k": 5,
  "filters": {},
  "stream": false,
  "retrieval_mode": "hybrid"
}
```

Fields:

- `query`: Required user question. After trimming whitespace, it must not be empty.
- `session_id`: Optional session identifier reserved for Web integration.
- `top_k`: Optional retrieval count. Default is `5`, valid range is `1-20`.
- `filters`: Optional retrieval filters. Default is `null`.
- `stream`: Optional streaming flag. Default is `false`; current version returns JSON.
- `retrieval_mode`: Optional retrieval mode. Supported values are `vector`, `bm25`, and `hybrid`; default is `hybrid`.

## Success Response

```json
{
  "trace_id": "trace-xxxxxxxx",
  "status": "success",
  "answer": "根据当前检索上下文，Q1 阶段主要需要打通用户提问、检索、Prompt 组装、答案生成和引用展示的基础链路。[1]",
  "message": "",
  "citations": [
    {
      "citation_id": 1,
      "title": "Agent 层 Q1 范围",
      "source_url": "https://example.local/docs/agent-q1-plan",
      "doc_id": "agent-q1-plan",
      "chunk_id": "chunk-001",
      "score": 0.96,
      "snippet": "Q1 只实现简化版单轮 RAG Agent，使用 Mock Retrieval 和 Mock LLM 打通最小闭环。"
    }
  ]
}
```

## Error Response

```json
{
  "trace_id": "trace-xxxxxxxx",
  "status": "invalid_query",
  "answer": "",
  "message": "请输入有效问题。",
  "citations": []
}
```

## Citations

- `citation_id`: Citation number starting from `1`.
- `title`: Source chunk title.
- `source_url`: Optional source URL.
- `doc_id`: Source document ID.
- `chunk_id`: Source chunk ID.
- `score`: Retrieval score.
- `snippet`: Short excerpt from `chunk_text` for Web display.

## Supported Status

- `success`
- `invalid_query`
- `no_relevant_context`
- `retrieval_error`
- `llm_error`

## Week 3 Quality Rules

- Empty or whitespace-only `query` returns `invalid_query` before retrieval or LLM calls.
- Empty retrieval results return `no_relevant_context` before LLM calls.
- Retrieval results below `MIN_RETRIEVAL_SCORE` are filtered out; if none remain, Agent returns `no_relevant_context`.
- Retrieval exceptions return `retrieval_error` with an empty answer and empty citations.
- LLM exceptions or empty LLM output return `llm_error` with an empty answer and empty citations.
- Success responses normalize answer references so bracketed citation IDs only point to existing citations.

## Prompt Trust Rules

The prompt requires the LLM to:

- answer only from retrieved context;
- avoid using outside knowledge;
- avoid inventing facts, numbers, workflows, owners, or dates;
- attach citation IDs to key claims;
- state that current materials are insufficient when context cannot support an answer.

## Tool Layer Integration

Agent uses `RetrievalAdapter` to call Tool Layer when `USE_MOCK_RETRIEVAL=false`.

Expected Tool Layer interface:

```python
SearchTool().search(
    query=query,
    top_k=top_k,
    mode=retrieval_mode,
    filters=filters,
    min_score=min_score,
    trace_id=trace_id,
)
```

The adapter converts Tool Layer `dict` results into `RetrievalResult` with:

- `doc_id`
- `chunk_id`
- `chunk_index`
- `chunk_text`
- `title`
- `source_url`
- `score`

Full Tool Layer contract is in `docs/tool_layer_interface.md`.

## Mode Switches

- `USE_MOCK_RETRIEVAL=true`: use built-in `MockRetrieval`.
- `USE_MOCK_RETRIEVAL=false`: dynamically load `TOOL_LAYER_IMPORT` / `TOOL_LAYER_CLASS`, defaulting to `tool_layer.SearchTool`.
- `USE_MOCK_LLM=true`: use built-in `MockLLM`.
- `USE_MOCK_LLM=false`: use `LLMClient` with OpenAI-compatible Chat Completions settings.

## Not Implemented In Current Version

- SSE streaming.
- ACL permission filtering.
- Production-level retrieval quality tuning.
- Production secret management.
