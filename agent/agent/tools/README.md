# Tool execution internals

`ToolExecutor.execute()` remains the public entry point used by Chat runners and
orchestration. It preserves `ToolExecutionResult` and existing error mappings.
The internal-only `direct_retrieval=True` flag selects `SearchTool.search_direct`
for Fast. It is not a model-visible argument or an authorization override.

| Module | Responsibility |
| --- | --- |
| `executor.py` | Tool lookup, validation, AccessGuard hooks, execution and result/error reporting |
| `argument_validation.py` | JSON parsing and the existing supported parameter-schema checks |
| `execution_pool.py` | Process-wide bounded workers, timeout waiting and ContextVar propagation |
| `result_adapters.py` | Tool-name dispatch and source-specific conversion to `Evidence` |
| `registry.py` | Read-only adapter over the Toolset-owned registry |

Source-specific adapters are ordinary functions in `result_adapters.py`, selected
by `_ADAPTERS`. Unknown tools use the generic adapter. `search_documents` uses
structured `search()` for Thinking; Fast requires `search_direct()` and fails
explicitly if unavailable. `read_attachment_context` uses the attachment adapter,
preserving original-file `content_kind`/hash and parsed excerpt provenance.
The result mapping is not a tool availability or authorization policy; in
particular it does not enable quarantined Wiki tools.

The lifecycle remains: validate → `prepare_tool` → run the adapter under a copy
of the request context → `capture_tool` → return. PermissionResolutionError is
propagated to terminate the turn. Other tool failures retain their structured error mapping.

Timeout bounds the caller's wait, not the lifetime of a running Python thread.
Queued work is cancelled where possible; running work keeps its capacity until
completion. No independent visual-model tool or special vision timeout remains.

`find_documents` returns catalog metadata only, with no citation Evidence.
`get_document(doc_ids=[...])` returns complete parsed documents in one call;
the adapter converts every returned source chunk to Evidence. No continuation
reader or hidden chunk-count limit remains. AccessGuard authorizes the entire
batch before reads and captures dependencies for every returned document.

Regression coverage is in `tests/unit/test_tool_executor.py` and
`tests/unit/test_tool_execution_boundaries.py`, alongside the source-specific
contract tests. These use fake tools and do not constitute real-source acceptance.
