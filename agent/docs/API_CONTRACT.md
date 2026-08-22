# API Contract

## POST /api/chat

Current stage: CP2 bounded Agent runtime with session memory, QueryPlan input,
dynamic tool schemas, retrieval quality gates, and citation consistency checks.

The endpoint runs the CP2 orchestration flow:

```text
request validation -> ConversationMemory -> QueryUnderstanding -> QueryPlan
-> IntentPolicyRouter -> AgentRunner -> ToolExecutor -> EvidenceGate
-> corrective retrieval (at most once) -> AnswerFormatter/CitationChecker
-> memory write-back -> JSON response
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
- `session_id`: Optional session identifier. Reusing it enables process-local
  short-term conversation memory.
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
- `clarification_required`
- `agent_limit_reached`
- `tool_error`
- `invalid_query`
- `no_relevant_context`
- `retrieval_error`
- `llm_error`
- `unsupported`

`clarification_required` keeps `answer` empty and puts the Agent's clarification
question in `message`, matching the existing Web error/status rendering path.

## Internal Persistent Memory contract (not a public endpoint)

The public `POST /api/chat` request and `ChatResponse` above remain unchanged.
They reject the internal-only `memory_context` field. The token-protected
`/api/internal/*` routes are introduced separately in Unit 04a; Unit 04 only
defines their Pydantic DTOs and configuration.

`InternalChatRequest` contains all existing `ChatRequest` fields plus a required
`memory_context`:

```text
InternalActor { user_id, authenticated: true }
MemoryMessage { id, sequence, revision, role, content }
MemorySnapshotInput { id, version, revision, covered_to_sequence, summary }
MemoryFactInput { id, category, value, expires_at: epoch-ms | null }
MemoryContextInput { actor, chat_id, revision, current_message_id,
                     current_sequence, snapshot: nullable, facts, tail }
```

The future internal chat response is
`InternalChatResponse { response: ChatResponse, memory_decision }`. Its
`memory_decision` may contain a `context_artifact`, `recall`, and
`fact_proposals`; `fact_proposals` is always an empty array through Units 01--08.
The compaction and short-window reset DTOs are also internal-only. BFF remains
the only writer of ChatMessage, Snapshot, and Fact records.

Persistent Memory is disabled by default with `PERSISTENT_MEMORY_ENABLED=false`.
`AGENT_INTERNAL_TOKEN` must be supplied only through environment configuration;
the example file intentionally leaves it empty. Unit 04a defines the constant-
time comparison, 403/409 behavior, and endpoint registration.

## Week 3 Quality Rules

- Empty or whitespace-only `query` returns `invalid_query` before retrieval or LLM calls.
- Empty retrieval results return `no_relevant_context` before LLM calls.
- Retrieval results below `MIN_RETRIEVAL_SCORE` are filtered out; if none remain, Agent returns `no_relevant_context`.
- Intent policies constrain candidate tools, iteration/tool/retrieval budgets,
  and retrieval strategy before the Runner executes.
- Evidence is accepted by `EvidenceGate` before final answer generation; a
  failed first attempt may trigger one bounded corrective retrieval.
- `CitationChecker` validates that exposed citations are backed by accepted
  request-local Evidence.
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

Agent Runner obtains tool schemas and tool instances from Tool Layer's
`ToolRegistry`. It accepts both the current CP1 names (`get_tool`,
`get_tool_schemas`) and the agreed CP2 names (`get`, `to_openai_schemas`) so the
two branches can be merged independently.

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

The Agent trust boundary converts Tool Layer `dict` results into
`RetrievalResult` with:

- `doc_id`
- `chunk_id`
- `chunk_index`
- `chunk_text`
- `title`
- `source_url`
- `score`

Full Tool Layer contract is in `docs/cp1/tool_layer_interface.md`.

The retrieval call always receives `standalone_query`, `top_k`,
`retrieval_mode`, hard `filters`, `MIN_RETRIEVAL_SCORE`, and the request
`trace_id`. Tests replace the LLM and search method with deterministic fakes;
production code contains no test-mode switch.

## Not Implemented In Current Version

- Production-level real LLM streaming.
- Cross-process or restart-persistent conversation memory.
- ACL permission filtering.
- Production-level retrieval quality tuning.
- Production secret management.

## Demo SSE Endpoint

`POST /api/chat/stream` is available for Q1 Web demo streaming UI. It returns `text/event-stream` events:

- `token`
- `citations`
- `done`

This endpoint reuses the normal chat response and emits demo streaming events. The stable integration contract remains `POST /api/chat`.

## GET /api/tools

Returns metadata from the Toolset-owned ToolRegistry through the Agent's
read-only adapter:

```json
[
  {
    "name": "search_documents",
    "description": "Search the document database...",
    "parameters": {
      "type": "object",
      "properties": {},
      "required": ["query"]
    },
    "enabled": true
  }
]
```

The OpenAI function-calling representation is available internally through
`registry.to_openai_schemas()` and is intentionally separate from this public
metadata response. See `docs/cp2/tool_registry.md` for the complete contract.

## GET /ready

Reports application-scoped resource initialization and retrieval warmup state.
It does not create a Chat turn or a Research Job:

```json
{
  "status": "ready",
  "initialized": true,
  "initialization_count": 1,
  "initialization_ms": 18,
  "retrieval_ready": true,
  "detail": ""
}
```

`status="degraded"` means the service remains alive for diagnostics but the
shared retrieval tool did not complete warmup. `/api/chat` continues to use the
existing public response contract.
