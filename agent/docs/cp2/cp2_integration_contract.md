# CP2 Agent Integration Contract

> Status: Draft, not frozen.
>
> If this document conflicts with a frozen component contract such as
> `query_plan_contract.md` or `tool_registry.md`, the frozen component contract
> and the latest CP2 optimization plan take precedence.

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

These components are implemented and tested, but are internal to future Query
Understanding:

```python
Clarifier.evaluate(query, history) -> ClarificationDecision
QueryRewriter.rewrite(query, history) -> RewriteResult
```

They are not final cross-module outputs. Query Understanding must combine their
results into one `QueryPlan`.

## 5. Contracts Still Pending Review

The following contracts are not frozen:

- ConversationMemory
- clarification state persistence
- IntentPolicy
- AgentState
- Evidence
- ToolExecutionResult
- RunSummary
- extended ChatResponse statuses

Code should not create incompatible final versions of these schemas before
team review.

## 6. ConversationMemory Requirements

The final interface still requires team confirmation, but it must support:

- strict isolation by `session_id`;
- single-turn compatibility when `session_id` is absent;
- message and token-budget truncation;
- persistent short-term storage;
- pending clarification state;
- no storage of private chain-of-thought;
- no storage of raw tool output as normal chat messages;
- execution metadata such as intent, rewritten query, and stop reason.

The final method signatures must be copied from the latest approved CP2 plan
before implementation is integrated.

## 7. Tool Execution Requirements

The future ToolExecutor must:

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

The future Evidence Gate must:

- reject empty evidence;
- remove results below the configured threshold;
- deduplicate by document and chunk identity;
- preserve filters and retrieval metadata;
- generate citations only from evidence used in final context;
- allow at most one corrective retrieval attempt;
- return `no_relevant_context` when evidence is still insufficient.

Intent-specific policies may require different evidence coverage.

## 9. Agent Runner Requirements

Agent Runner must enforce:

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

## 11. Current Team Checklist

- [x] QueryIntent values are frozen.
- [x] QueryPlan fields and validation are frozen.
- [x] Toolset is the only ToolRegistry owner.
- [x] Agent uses a read-only ToolRegistryAdapter.
- [x] QueryRewriter has safe fallback behavior.
- [x] Clarifier has safe fallback behavior.
- [ ] ConversationMemory contract is reviewed.
- [ ] IntentPolicy contract is reviewed.
- [ ] AgentState contract is reviewed.
- [ ] Evidence and ToolExecutionResult are reviewed.
- [ ] RunSummary and extended API statuses are reviewed.
- [ ] Mock integration tests cover the complete CP2 flow.
