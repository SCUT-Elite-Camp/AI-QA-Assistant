# CP2 Agent Integration Contract

> Status: Integrated baseline (2026-07-30).
>
> This document records the CP2 cross-workstream baseline after partner PR #17
> and Workstream 1 were merged into `agent-dev`. Component contracts remain
> authoritative for field-level details.

## 1. Purpose

This document tracks integration points between the two Agent developers while
CP2 schemas are frozen incrementally.

- Developer A owns conversation state and Agent runtime.
- Developer B owns query understanding and answer quality.
- Both developers own shared schemas, integration tests, API compatibility,
  and final review.

Internal implementation may change independently, but public schemas and call
order must not change without review.

## 2. Target Flow

```text
Receive ChatRequest
    ↓
Validate query and create trace_id
    ↓
Load conversation history and pending clarification state
    ↓
Query Understanding
    ↓
QueryPlan
    ├─ clarification required → save turn and return
    └─ executable plan
         ↓
       PolicyRouter
         ↓
       IntentPolicy
         ↓
       Agent Runner
         ↓
       ToolRegistryAdapter / ToolExecutor
         ↓
       Evidence Gate
         ↓
       Final answer and citation validation
         ↓
       Save conversation and RunSummary
```

Required invariants:

1. Retrieval uses `QueryPlan.standalone_query`.
2. Final answer generation and Memory preserve
   `QueryPlan.original_query`.
3. Clarification prevents tool execution.
4. One request uses one `trace_id` across all stages.
5. Model output cannot override policy budgets or tool allowlists.

## 3. Frozen Contracts

The following contracts are currently frozen:

### QueryIntent and QueryPlan

See `query_plan_contract.md`.

### ToolRegistry Ownership

See `tool_registry.md`.

Toolset is the only ToolRegistry owner. Agent uses a read-only adapter and must
not maintain a second tool mapping.

## 4. Implemented Internal Components

These components are implemented and invoked by Query Understanding:

```python
Clarifier.evaluate(query, history) -> ClarificationDecision
QueryRewriter.rewrite(query, history) -> RewriteResult
```

They are not final cross-module outputs. Query Understanding must combine their
results into one `QueryPlan`.

## 5. Contract and implementation status

The CP2 implementation now contains the following internal contracts and
runtime components:

- `ConversationMemory`, `AgentState`, `AgentRunResult`, and stop reasons;
- `IntentPolicy`, `Evidence`, and `ToolExecutionResult` models;
- Query Understanding, policy routing, tool execution, evidence gate, and
  citation validation components;
- the bounded `AgentRunner` and `Agent.chat(..., query_plan=...)` boundary.

The five-field `ChatResponse` remains the only public Web response contract.
Any future public schema change still requires a coordinated review.

## 6. ConversationMemory Requirements

The CP2 interface supports:

- strict isolation by `session_id`;
- single-turn compatibility when `session_id` is absent;
- message and token-budget truncation;
- process-local short-term storage;
- clarification state represented by the stored user/question turn;
- no storage of private chain-of-thought;
- no storage of raw tool output as normal chat messages;
- execution metadata such as intent, rewritten query, and stop reason.

The method signatures are implemented in `agent/memory/base.py` and covered by
unit and integration tests.

## 7. Tool Execution Requirements

The orchestrated ToolExecutor:

- resolve tools through `ToolRegistryAdapter`;
- parse tool arguments as JSON objects;
- validate arguments against the tool schema;
- enforce timeout and policy limits;
- propagate `trace_id`;
- map failures to structured errors;
- return results without shared mutable state.

The Agent must stop relying on `SearchTool.latest_results`. Evidence must be
returned with the current tool execution result.

## 8. Evidence Requirements

The orchestrated Evidence Gate:

- reject empty evidence;
- remove results below the configured threshold;
- deduplicate by document and chunk identity;
- preserve filters and retrieval metadata;
- generate citations only from evidence used in final context;
- allow at most one corrective retrieval attempt;
- return `no_relevant_context` when evidence is still insufficient.

Intent-specific policies may require different evidence coverage.

## 9. Agent Runner Requirements

With an `IntentPolicy`, Agent Runner enforces:

- maximum iterations;
- maximum tool calls;
- maximum retrieval attempts;
- total runtime;
- per-tool timeout;
- repeated tool-call protection;
- policy tool allowlists;
- explicit stop reasons.

The model must not be able to expand these budgets.

## 10. Testing Boundaries

Default Agent tests must not require:

- Milvus;
- embedding model downloads;
- Ollama;
- external network access.

Tests should use injected fake implementations for LLM, tools, memory, query
understanding, and policy.

Real Toolset and persistence tests must be marked and run separately.

## 11. CP2 completion checklist (2026-07-30)

- [x] QueryIntent values are frozen.
- [x] QueryPlan fields and validation are frozen.
- [x] Toolset is the only ToolRegistry owner.
- [x] Agent uses a read-only ToolRegistryAdapter.
- [x] QueryRewriter has safe fallback behavior.
- [x] Clarifier has safe fallback behavior.
- [x] ConversationMemory, AgentState, Evidence, and ToolExecutionResult are implemented.
- [x] Agent Runner consumes QueryPlan and enforces bounded execution.
- [x] Mock integration tests cover memory, clarification, filters, and Runner flow.
- [x] AgentOrchestrator wires QueryUnderstanding, PolicyRouter, ToolExecutor,
  EvidenceGate, corrective retrieval, and CitationChecker into Chat.
- [ ] Durable multi-worker memory remains post-CP2 hardening work; the current
  memory is intentionally process-local.
