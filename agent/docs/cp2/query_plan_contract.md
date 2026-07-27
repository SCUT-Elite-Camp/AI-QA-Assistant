# QueryPlan Public Contract (CP2)

Workstream 2 produces `QueryPlan`, and Workstream 1's `AgentRunner.run`
consumes it directly. The only executable model source is:

```text
agent/schemas/query_plan.py
```

## Python Interface

```python
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class QueryIntent(StrEnum):
    KNOWLEDGE_QA = "knowledge_qa"
    DOCUMENT_SEARCH = "document_search"
    SUMMARIZATION = "summarization"
    COMPARISON = "comparison"
    CASUAL_CHAT = "casual_chat"
    SYSTEM_HELP = "system_help"
    UNSUPPORTED = "unsupported"


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_query: str
    standalone_query: str
    intent: QueryIntent = QueryIntent.KNOWLEDGE_QA
    intent_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    is_follow_up: bool = False
    is_clarification_reply: bool = False
    needs_clarification: bool = False
    clarification_question: str = ""
    ambiguity_reason: str = ""
    sub_queries: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
```

## Semantic Rules

- `original_query` must exactly match the current `ChatRequest.query`. It is
  used for conversation, memory, and auditing.
- `standalone_query` is the independently retrievable query after trimming
  leading and trailing whitespace. Runner retrieval tools use only this field.
- Empty `sub_queries` are removed. The current CP2 Runner does not
  automatically execute sub-queries in parallel.
- `filters` are hard constraints. Chat may add missing request filters, but a
  same-name conflict must reject the request. Runner must not silently overwrite
  or remove either constraint.
- When `needs_clarification=true`, `clarification_question` is required and
  Runner does not execute tools.
- When `needs_clarification=false`, `clarification_question` is normalized to
  an empty string.
- Undeclared fields are rejected to prevent silent contract drift.

## Runner Calls

```python
result = agent.run_plan(
    query_plan,
    history=memory.get_messages(session_id),
    trace_id=trace_id,
    mode=request.retrieval_mode,
    top_k=request.top_k,
)
```

Through Chat orchestration:

```python
response = agent.chat(request, query_plan=query_plan)
```

Chat orchestration validates `original_query`, merges filters, loads
conversation history, and writes successful or clarification turns to memory.

## Compatibility Import

Internal Query Understanding components may continue importing from
`agent.query`, which re-exports the same canonical classes:

```python
from agent.query import QueryIntent, QueryPlan
```

This is an alias, not a second schema definition.
