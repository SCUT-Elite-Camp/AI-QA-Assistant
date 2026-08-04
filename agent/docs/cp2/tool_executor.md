# ToolExecutor Contract

## Purpose

`ToolExecutor` is the only Agent-side component that executes Toolset-owned
tools. It accepts a tool call and always returns a request-local
`ToolExecutionResult`.

```python
result = executor.execute(
    tool_call_id="call-1",
    tool_name="search_documents",
    arguments={
        "query": query_plan.standalone_query,
        "top_k": policy.top_k,
        "mode": policy.retrieval_strategy,
        "filters": query_plan.filters,
    },
    trace_id=trace_id,
    retrieval_attempt=1,
)
```

## Responsibilities

- Resolve a tool through the read-only `ToolRegistryAdapter`.
- Parse JSON arguments.
- Validate required fields, JSON types, enums, numeric bounds, and explicitly
  forbidden additional properties.
- Apply `TOOL_TIMEOUT_MS`.
- Map failures into stable error codes.
- Propagate `trace_id` to structured retrieval.
- Convert retrieval rows into `Evidence`.
- Emit structured execution logs.

## Structured Results

```python
class ToolExecutionResult(BaseModel):
    tool_call_id: str
    tool_name: str
    success: bool
    data: dict[str, Any] | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    error_code: str = ""
    error_message: str = ""
    elapsed_ms: int = 0
```

`Evidence` records document identity, content, normalized score, retrieval
query, retrieval mode, and retrieval attempt.

## SearchTool Compatibility

For `search_documents`, ToolExecutor calls the structured `search(...)` method
instead of the legacy text-returning `execute(...)` method. Evidence is returned
directly with the current tool call.

ToolExecutor never reads, clears, or writes `SearchTool.latest_results`.

## Error Codes

| Code | Meaning |
|---|---|
| `tool_not_found` | Toolset does not currently expose the requested tool |
| `invalid_arguments` | Arguments are invalid JSON or violate the tool schema |
| `tool_timeout` | Execution exceeded `TOOL_TIMEOUT_MS` |
| `invalid_tool_result` | Tool output cannot satisfy the Agent result contract |
| `tool_execution_failed` | The tool raised an execution exception |

Errors are returned as data and do not escape directly into Agent Runner.
