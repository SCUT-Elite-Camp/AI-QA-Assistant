# Agent Layer CP2 Optimization Plan

> Scope: CP2 development for the AI-QA-Assistant Agent layer  
> Baseline branch: `agent-dev`; synchronize the latest `dev` before development  
> Team: two Agent developers  
> Duration: approximately two weeks, including cross-layer integration  
> Core approach: the LLM handles semantic understanding, while rule-based policies control execution

## 1. Background

CP1 completed the single-turn RAG question-answering loop, but the following limitations remain:

- No conversation memory across requests.
- No formal intent recognition or task routing.
- Ambiguous questions cannot trigger proactive clarification.
- Original user queries enter retrieval directly, without reference resolution or query rewriting.
- Agent loops have limited controls and lack reliable stopping mechanisms.
- Different query types use the same retrieval and answer flow.
- Tool results depend on `SearchTool.latest_results`, creating a risk of cross-request contamination.
- Parameters such as `filters` and `trace_id` are not propagated end to end.
- Evidence quality is evaluated too late, so the generation model may be called with insufficient evidence.
- Toolset already owns a `ToolRegistry`; the Agent must not implement a duplicate registry.

The CP2 goal is to upgrade the system into:

> A RAG Agent with conversation memory, intent recognition, rule-based routing, proactive clarification, query rewriting, controlled multi-step execution, and evidence quality assurance.

---

## 2. Core CP2 Design Principles

### 2.1 Semantic Understanding Is Handled by the LLM

The LLM is primarily responsible for:

- Intent recognition.
- Reference resolution.
- Ambiguity detection.
- Query rewriting.
- Complex-query decomposition.
- Clarification-question generation.

### 2.2 Execution Control Is Handled by Rules

Rule-based policies determine:

- Whether tools should be called.
- Which tools are allowed.
- Which retrieval strategy should be used.
- The value of `top_k`.
- The maximum number of iterations.
- The maximum number of tool calls.
- Evidence acceptance conditions.
- Answer format.
- Timeout and repeated-call limits.

The model must not be able to bypass these limits.

### 2.3 CP2 Will Not Build a Complete Skills System

CP2 uses:

```text
Intent → QueryPlan → IntentPolicy → Agent Runner
```

After different task flows have been tested and stabilized, CP3 can package them as:

```text
KnowledgeQASkill
DocumentSearchSkill
SummarizationSkill
ComparisonSkill
```

---

## 3. CP2 Goals and Non-Goals

### 3.1 P0: Required

1. Persistent short-term conversation memory based on `session_id`.
2. Intent recognition and Query Understanding.
3. Intent-based Policy Routing.
4. Contextual reference resolution and query rewriting.
5. Proactive clarification for ambiguous queries and clarification-state recovery.
6. A ReAct-lite execution loop constrained by hard budgets.
7. Consumption of the `ToolRegistry` provided by Toolset.
8. Tool execution results without shared mutable state.
9. End-to-end propagation of `query`, `filters`, `trace_id`, and retrieval parameters.
10. An Evidence Gate before final answer generation.
11. At most one corrective retrieval when evidence is insufficient.
12. Citation consistency validation.
13. Structured execution logs and stop reasons.
14. Synchronized Web, Agent, Toolset, and Data Persistence interfaces.
15. Automated tests and a basic evaluation set.

### 3.2 P1: Optional

1. Multi-query retrieval and RRF fusion.
2. Neighboring-chunk expansion.
3. Lightweight reranking.
4. Conversation-history summarization.
5. Dynamic prompt assembly.
6. Intent-based candidate-tool filtering.
7. Document version-conflict and freshness checks.
8. Answer-confidence indicators.
9. True SSE step and token streaming.
10. User-feedback statistics API.

### 3.3 Out of Scope for This Iteration

- A complete Skills system.
- Multi-Agent collaboration.
- Long-term user profiles and automatic experience learning.
- Direct Agent connections to Milvus, BM25, or Confluence.
- Dynamic MCP and OpenAPI tools.
- Code-as-Action.
- Unlimited Agent loops.
- Exposing the model's raw Chain-of-Thought to the frontend.
- A complete production-grade identity and permission system.

---

## 4. Target Architecture

```text
User query + session_id
        ↓
Load conversation history and pending clarification state
        ↓
Query Understanding
  ├── Intent recognition
  ├── Reference resolution
  ├── Ambiguity detection
  ├── Query rewriting
  └── Complex-query decomposition
        ↓
Generate QueryPlan
        ↓
Policy Router
  ├── Fast response
  ├── Proactive clarification
  ├── Single-pass RAG
  └── Complex-task Runner
        ↓
Filter candidate tools according to policy
        ↓
ToolExecutor executes tools
        ↓
Evidence Gate
  ├── Evidence accepted → final generation
  ├── First rejection → correct query and retrieve once more
  └── Second rejection → no_relevant_context
        ↓
Citation validation
        ↓
Save conversation, run summary, and metrics
```

---

## 5. Intent Recognition

### 5.1 Core Intents Supported by CP2

```python
class QueryIntent(StrEnum):
    KNOWLEDGE_QA = "knowledge_qa"
    DOCUMENT_SEARCH = "document_search"
    SUMMARIZATION = "summarization"
    COMPARISON = "comparison"
    CASUAL_CHAT = "casual_chat"
    SYSTEM_HELP = "system_help"
    UNSUPPORTED = "unsupported"
```

Two additional properties are used:

```text
is_follow_up
is_clarification_reply
```

### 5.2 Policies for Different Intents

| Intent | Retrieval | Evidence Requirement | Answer Format |
|---|---|---|---|
| `knowledge_qa` | Hybrid | At least one valid item of evidence | Concise Q&A |
| `document_search` | Metadata/BM25 | Accurate document identity and source | Document list |
| `summarization` | Hybrid with a larger `top_k` | Coverage of multiple topics | Structured summary |
| `comparison` | Multi-query Hybrid | Evidence for both comparison targets | Comparison table |
| `casual_chat` | No retrieval | None | Direct response |
| `system_help` | No retrieval or fixed capability configuration | None | Capability description |
| `unsupported` | No tool calls | None | Unsupported-task notice |

---

## 6. Query Understanding and QueryPlan

Query Understanding performs:

- Intent recognition.
- Reference resolution.
- Clarification decisions.
- Query rewriting.
- Sub-query generation.
- Filter extraction.

Recommended output:

```python
class QueryPlan(BaseModel):
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

Constraints:

- Do not trigger clarification when the reference can be resolved from history.
- When the user's intent cannot be determined safely, ask only one specific clarification question.
- Fall back to the original query if rewriting fails.
- Do not add facts or conditions that the user did not provide.
- Answer the original query, but use `standalone_query` for retrieval.
- If Query Understanding fails, safely fall back to `knowledge_qa + hybrid`.

---

## 7. Policy Routing

### 7.1 IntentPolicy

```python
class IntentPolicy(BaseModel):
    candidate_tools: list[str] = Field(default_factory=list)

    retrieval_strategy: str = "hybrid"
    evidence_policy: str = "single_fact"
    assembly_strategy: str = "score_order"
    answer_style: str = "concise_qa"

    top_k: int = 5
    max_iterations: int = 3
    max_tool_calls: int = 2
    max_retrieval_attempts: int = 2

    requires_citations: bool = True
```

### 7.2 Routing Examples

```text
knowledge_qa
→ search_documents
→ Hybrid
→ top_k=5
→ single_fact Evidence
→ concise answer

comparison
→ search_documents
→ multi-sub-query Hybrid
→ bilateral Evidence coverage
→ comparison answer

casual_chat
→ no tools
→ no retrieval
→ direct answer

unsupported
→ no tools
→ do not enter Runner
→ return capability boundary
```

Policies are configured through allowlists. The LLM must not generate arbitrary tool names, budgets, or strategies.

---

## 8. Conversation Memory and the Clarification Loop

### 8.1 ConversationMemory

```python
class ConversationMemory(Protocol):
    def get_messages(
        self,
        session_id: str,
        limit: int,
    ) -> list[ConversationMessage]: ...

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        **metadata,
    ) -> ConversationMessage: ...

    def clear(self, session_id: str) -> int: ...

    def truncate(
        self,
        session_id: str,
        after_message_id: str | None,
    ) -> int: ...
```

### 8.2 Memory Requirements

- Use the Web chat ID as `session_id`.
- Strictly isolate different sessions.
- Preserve single-turn compatibility when `session_id` is absent.
- CP2 should use SQLite or a persistent implementation provided by Data Persistence.
- Truncate by both message count and token budget.
- Do not store the model's private reasoning.
- Do not store raw tool results as ordinary chat messages.
- Store execution summaries such as intent, rewritten query, and stop reason.

### 8.3 Clarification State

The following information must be stored:

```text
Original query
Missing information
Clarification question asked by the Agent
Whether the Agent is waiting for user input
```

Example:

```text
User: Help me compare them.
Agent: Which objects would you like to compare?
User: Q1 and CP2.
```

The system should recover the task as:

```text
Compare Q1 and CP2.
```

It must not retrieve only `"Q1 and CP2"` as an independent query.

---

## 9. Controlled Agent Runner

The Agent Runner is responsible for:

- Consuming QueryPlan and IntentPolicy.
- Calling the LLM.
- Handling `tool_calls`.
- Executing tools through ToolExecutor.
- Adding tool observations to messages.
- Stopping when no `tool_calls` are returned.
- Keeping the same `trace_id` throughout the flow.

### 9.1 Stop Conditions

1. The LLM returns a final answer without `tool_calls`.
2. QueryPlan requires clarification.
3. Evidence is insufficient after one corrective retrieval.
4. The maximum iteration count is reached.
5. The total runtime limit is reached.
6. The maximum tool-call count is reached.
7. The same tool is called repeatedly with the same arguments.
8. The LLM or a tool encounters an unrecoverable error.

### 9.2 Recommended Configuration

```env
MEMORY_ENABLED=true
MAX_MEMORY_MESSAGES=12
MAX_MEMORY_TOKENS=4000

QUERY_UNDERSTANDING_ENABLED=true
CLARIFICATION_ENABLED=true

MAX_AGENT_ITERATIONS=4
MAX_TOOL_CALLS=4
MAX_RETRIEVAL_ATTEMPTS=2
MAX_REPEATED_TOOL_CALLS=2
MAX_AGENT_RUNTIME_MS=15000
TOOL_TIMEOUT_MS=10000
```

Each intent may use a smaller budget than the global limit.

---

## 10. Tool Registration and Execution

### 10.1 ToolRegistry Ownership

- Toolset is the sole owner of `ToolRegistry`.
- The Agent must not build a second registry.
- The Agent reads tools and OpenAI Tool Schemas through an adapter.
- `/api/tools` continues to read from the Toolset registry.

### 10.2 ToolExecutor

The Agent adds a ToolExecutor responsible for:

- Looking up tools by name.
- Parsing argument JSON.
- Validating argument schemas.
- Enforcing timeouts.
- Propagating `trace_id`.
- Mapping errors.
- Producing structured logs.
- Converting results into `ToolExecutionResult`.

### 10.3 Structured Tool Results

```python
class Evidence(BaseModel):
    doc_id: str
    chunk_id: str
    chunk_index: int = 0
    title: str
    content: str
    source_url: str = ""
    score: float

    retrieval_query: str
    retrieval_mode: str
    retrieval_attempt: int = 1


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

Tool results must be returned with the current call and must no longer depend on `latest_results`.

---

## 11. Evidence Gate and Corrective Retrieval

### 11.1 Basic Rules

- Do not call final generation when no Evidence is available.
- Discard results below the score threshold.
- Deduplicate by `doc_id + chunk_id`.
- Generate Citations only for Evidence that actually enters the final context.
- Pass `filters` to SearchTool.
- Record the original query, rewritten query, retrieval mode, scores, and elapsed time.

### 11.2 Intent-Specific Evidence Requirements

```text
knowledge_qa
→ at least one valid item of evidence

summarization
→ coverage of multiple major topics

comparison
→ evidence for both comparison targets

document_search
→ valid document titles and sources
```

### 11.3 Corrective Retrieval

When Evidence fails the first evaluation, the Agent may:

- Adjust the query.
- Relax non-mandatory filters.
- Switch between BM25, Vector, and Hybrid retrieval.
- Retrieve only the missing comparison target.

If Evidence still fails the second evaluation, return:

```text
no_relevant_context
```

The system must not continue looping in the hope of finding a result.

---

## 12. Dynamic Prompts and Answer Policies

Prompts are assembled from multiple blocks:

```text
Common system rules
+ current-intent rules
+ conversation context
+ available tools
+ Evidence
+ citation rules
+ output format
```

Different intents use different answer formats:

- Knowledge Q&A: concise answer.
- Document search: document list.
- Summarization: topic-based summary.
- Comparison: comparison table.
- Clarification: ask only one question.
- System help: describe only actual capabilities.
- Unsupported tasks: clearly state the capability boundary.

Dynamic prompts and tool filtering may remain P1. At P0, different intents must at least enter different execution paths.

---

## 13. API Extensions

Preserve the CP1 fields and add an optional run summary:

```python
class RunSummary(BaseModel):
    stop_reason: str
    intent: str
    iterations: int = 0
    tool_calls: int = 0
    retrieval_attempts: int = 0
    elapsed_ms: int = 0


class ChatResponse(BaseModel):
    trace_id: str
    status: str
    answer: str
    message: str
    citations: list[Citation]
    run: RunSummary | None = None
```

New statuses:

```text
clarification_required
agent_limit_reached
tool_error
unsupported
```

Clarification example:

```json
{
  "trace_id": "trace-xxxx",
  "status": "clarification_required",
  "answer": "",
  "message": "Which two versions would you like to compare?",
  "citations": [],
  "run": {
    "stop_reason": "clarification_required",
    "intent": "comparison",
    "iterations": 0,
    "tool_calls": 0,
    "retrieval_attempts": 0,
    "elapsed_ms": 120
  }
}
```

---

## 14. Work Allocation

### Workstream 1: Conversation State and Agent Runtime

Responsibilities:

- ConversationMemory.
- Clarification-state storage and recovery.
- AgentState.
- Controlled Agent Runner.
- Iteration, timeout, and tool-call limits.
- Repeated-tool-call protection.
- Chat API integration.
- Run summaries and Trace.
- Multi-turn conversation and stop-condition tests.

Estimated effort: approximately nine person-days.

### Workstream 2: Query Understanding and Answer Quality

Responsibilities:

- Intent recognition.
- Reference resolution.
- Query rewriting.
- QueryPlan.
- IntentPolicy and Policy Routing.
- ToolRegistry adapter.
- ToolExecutor.
- Evidence Gate.
- Corrective retrieval.
- Citation validation and evaluation.

Estimated effort: approximately nine person-days.

### Shared Responsibilities

- Freeze public schemas on Day 1.
- Repair the CP1 test baseline.
- Review Web, Toolset, and Persistence interfaces.
- Integration testing.
- Demo and documentation.
- PR review and final acceptance.

---

## 15. Two-Week Implementation Schedule

### Day 1: Baseline and Contract Freeze

- Synchronize the latest `dev` into `agent-dev`.
- Repair the existing test baseline.
- Freeze QueryPlan, IntentPolicy, AgentState, Evidence, ToolExecutionResult, and ChatResponse.
- Create two feature branches.

### Days 2–4: First Parallel Development Phase

Workstream 1:

- ConversationMemory.
- AgentState.
- Basic Runner loop.

Workstream 2:

- Query Understanding.
- Intent recognition.
- QueryPlan and Policy Routing.
- Basic ToolExecutor capabilities.

### Day 5: First Integration

- Connect conversation history.
- Connect intent recognition and rule-based routing.
- Connect one tool call through to the final answer.
- Verify parameter and `trace_id` propagation.

### Days 6–7: Reliability Improvements

Workstream 1:

- Timeout, iteration, and repeated-call protection.
- Clarification-state recovery.
- Run summaries.

Workstream 2:

- Evidence Gate.
- One corrective retrieval.
- Citation validation.
- Intent-specific Evidence rules.

### Day 8: Cross-Layer Integration

- Web passes `session_id`.
- Web displays clarification status.
- Toolset returns structured Evidence.
- Persistence stores conversation messages.
- Smoke-test real tools.

### Day 9: Testing and Evaluation

- Multi-turn references.
- Proactive clarification.
- Intent routing.
- Query rewriting.
- Comparison and summarization.
- Refusal when no Evidence is available.
- Repeated-call and timeout behavior.

### Day 10: Documentation and Merge

- Run the complete pytest suite.
- Check API contracts.
- Update the README and architecture documentation.
- Update the integration record.
- Submit the `agent-dev → dev` pull request.

---

## 16. Minimum Acceptance Scenarios

### Conversation Follow-Up

```text
Turn 1: Introduce the Agent layer.
Turn 2: What are its limitations?
```

Expected:

- Recognized as `knowledge_qa`.
- `is_follow_up=true`.
- Rewrite `"it"` as `"the Agent layer"`.
- Retrieve and answer normally.

### Ambiguous Comparison

```text
Help me compare them.
```

Expected:

- Recognized as `comparison`.
- Return `clarification_required`.
- Do not call retrieval tools.

### Clarification Reply

```text
Previous turn: Which objects would you like to compare?
Current turn: Q1 and CP2.
```

Expected:

- Recover the original task.
- Generate separate sub-queries for Q1 and CP2.
- Generate a comparison only after Evidence is available for both sides.

### Casual Conversation

```text
Hello.
```

Expected:

- Recognized as `casual_chat`.
- Do not call SearchTool.
- Respond directly.

### Query Without Evidence

Expected:

- Perform one correction after the first Evidence failure.
- Return `no_relevant_context` if the second attempt also fails.
- Do not call the final generation model.

### Repeated Tool Calls

Expected:

- Stop after reaching the repetition limit.
- Return an explicit `stop_reason`.
- Never enter an infinite loop.

---

## 17. CP2 Definition of Done

CP2 is complete only when all of the following conditions are met:

- The Web chat ID is passed to the Agent as `session_id`.
- Conversation memory works across requests, and different sessions remain isolated.
- Intent recognition materially changes the downstream execution path.
- Clarification, reference resolution, and query rewriting use one unified QueryPlan.
- Policy Routing selects tools, retrieval strategy, Evidence requirements, and execution budgets.
- Ambiguous questions do not trigger retrieval.
- Casual conversation does not enter the complete RAG flow.
- Agent iteration, timeout, and tool-call limits are enforced in practice.
- The Agent consumes the Toolset Registry directly.
- Tool results no longer depend on `latest_results`.
- `filters` and `trace_id` are propagated end to end.
- Final generation is not called without valid Evidence.
- Corrective retrieval occurs at most once.
- Every Citation maps to real Evidence.
- Execution includes structured logs and a `stop_reason`.
- Default tests and cross-layer interface tests all pass.
- The API, README, and implementation remain consistent.

Final evolution:

```text
CP1: Single-turn RAG
  ↓
CP2: Intent recognition + Policy Routing + controlled Agent
  ↓
CP3: Package stable task flows as Skills
```
