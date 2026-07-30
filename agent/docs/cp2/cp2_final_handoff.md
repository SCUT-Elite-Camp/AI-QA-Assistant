# CP2 Agent Final Handoff

> Baseline: 2026-07-30 · target branch: `agent-dev`

## Outcome

CP2 Agent workstreams are merged into `agent-dev`:

- Partner PR #17: Query Understanding, QueryPlan/QueryIntent, clarification,
  query rewriting/planning, policy routing, ToolRegistryAdapter, structured
  ToolExecutor, Evidence Gate, corrective retrieval, and citation checks.
- Workstream 1: process-local `ConversationMemory`, bounded `AgentRunner`,
  `AgentState`/stop reasons, QueryPlan consumption, ChatResponse mapping, and
  memory-flow tests.

The public Web response remains backward compatible (`trace_id`, `status`,
`answer`, `message`, `citations`). Retrieval uses `standalone_query`; the
original query is retained for history and audit records.

## Verification

Run from the repository root:

```powershell
D:\ix\ai\AI-QA-Assistant\.venv\Scripts\python.exe -m pytest agent/tests/unit agent/tests/integration/test_cp2_memory_flow.py -q
```

Result on 2026-07-30: **196 passed**, with only dependency deprecation
warnings from `pymilvus` and `environs`.

The complete Agent suite (`pytest agent/tests -q`) also passed **205 tests**.
The adjacent Toolset suite passed **13 tests**. Data Persistence passed **1
test** and skipped **2** environment-dependent tests (Milvus/service setup).

The partner branch's historical report (`agent/docs/cp2/local_unit_test_report.xlsx`)
records its pre-integration 171-test run (168 passed and 3 external embedding
environment failures). The 196-test command above is the merged baseline and
should be used for CP2 regression checks.

## Runtime boundaries

- Memory is thread-safe but process-local; it is not shared across workers or
  restarts.
- `session_id` is required for memory reads/writes; empty session IDs stay
  stateless.
- QueryPlan filters supplied by the request are treated as hard constraints.
- Toolset remains the sole owner of tool registration; Agent consumes its
  read-only adapter.
- Generated presentation files and draft planning notes are kept outside the
  repository under `D:\ix\ai\outputs\cp2-artifacts-20260730`.

## Recommended follow-up

For the next iteration, wire `QueryUnderstanding` and `IntentPolicyRouter`
directly into the Web chat orchestration, then add a durable memory backend and
an end-to-end evaluation set. These are intentionally not prerequisites for
the merged CP2 in-process baseline.
