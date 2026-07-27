# IntentPolicy and Policy Routing

## Purpose

`IntentPolicyRouter` converts a validated `QueryIntent` into an immutable,
allowlisted execution policy. It does not call an LLM.

```text
QueryPlan.intent
        ↓
IntentPolicyRouter
        ↓
candidate tools + retrieval + Evidence rule + budgets + answer style
```

## Safety Boundary

- Tool names come only from code-owned allowlists.
- Retrieval attempts are capped at two.
- Casual chat, system help, and unsupported requests receive zero tool budget.
- Policy objects are immutable after creation.
- Unknown policy fields and out-of-range budgets are rejected.

## Current Routing

| Intent | Tool | Retrieval | Evidence | Answer |
|---|---|---|---|---|
| `knowledge_qa` | `search_documents` | Hybrid | Single fact | Concise Q&A |
| `document_search` | `search_documents` | BM25 | Document identity | Document list |
| `summarization` | `search_documents` | Hybrid | Topic coverage | Structured summary |
| `comparison` | `search_documents` | Hybrid | Bilateral coverage | Comparison table |
| `casual_chat` | None | None | None | Direct chat |
| `system_help` | None | None | None | Capability help |
| `unsupported` | None | None | None | Capability boundary |
