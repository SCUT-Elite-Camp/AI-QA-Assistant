# Web-Agent Interface Contract

Current access/lineage contract (2026-10-09): [integration guide](../../docs/access-evidence-integration.md). Browsers use session-authenticated same-origin BFF routes, not a public Agent URL/token. Source permissions are rechecked for retrieval, model calls, release and stored history/Memory/Reader. `evidence.provenance.v1` is part of the response; unknown/stale lineage is not trusted.

## Local Deep Research

Local Deep Research is separate from Chat and must be manually started.

```text
POST /api/research/jobs
GET  /api/research/jobs/{research_id}
GET  /api/research/jobs/{research_id}/plan
POST /api/research/jobs/{research_id}/approve
POST /api/research/jobs/{research_id}/cancel
GET  /api/research/jobs/{research_id}/report
GET  /api/research/jobs/{research_id}/progress
GET  /api/research/jobs/{research_id}/events?after_event_id={event_id}&limit={limit}
```

`POST /api/research/jobs` durably creates a Job and immediately returns it with
`status=created`. The Web client polls the Job endpoint until
`awaiting_approval`, displays the current Plan, and approves using both
`plan_version` and `manifest_hash`. A stale version or changed source snapshot
returns HTTP 409. The final execution status is `completed`, `failed`, or
`cancelled`; a completed report separately declares `complete` or `degraded`.

This API does not accept Web URLs. The Worker can only search and read document
IDs frozen into the approved `SourceManifest`.

Current Research scope is enterprise Confluence only. A manifest freezes content, not permission: native mapping and local/native ACL must still allow it. Creation requires trusted `X-User-ID`; resources belong to that creator. Other users get 404; revoked sources, unavailable permission checks or version drift block report/progress/events/trace/source access. Worker search/read uses the shared enterprise Toolset and requested retrieval mode.

The Research detail page polls three independent views at low frequency:

- `GET /jobs/{id}` for lifecycle controls;
- `GET /jobs/{id}/progress` for the authoritative percentage, stage timeline,
  task states, counts, and safe terminal error;
- `GET /jobs/{id}/events` with `after_event_id` for recent incremental activity.

The frontend must render `progress_percent`, `stages`, and `tasks` as returned;
it must not infer a second state machine from Job status or array position.
Polling stops when `status` is `completed`, `failed`, or `cancelled`.

### Research conversation commands

`POST /api/research/jobs/{id}/messages` accepts `{ "message": "采用来源 2" }`
for a completed report with a matching conflict alternative. It persists a new
report revision, marks the selected conflict `resolved_by_user`, and retains
the original evidence and citations. A user choice records a decision; it does
not reverify claims or clear existing quality limitations. Unknown source
numbers return `action=clarify` without revising the report. Clients should
reload the report after `action=conflict_resolved`.

The conflict-choice persistence, invalid-source behavior, and preservation of
quality gaps are covered by `test_research_control_plane_api.py`.

## POST `/api/chat`

Request:

```json
{
  "query": "What features are required for project Q1?",
  "session_id": "optional-session-id",
  "top_k": 5,
  "filters": null,
  "stream": false,
  "retrieval_mode": "hybrid"
}
```

Fields:

- `query`: required user query.
- `session_id`: optional conversation identifier.
- `top_k`: number of retrieval results; defaults to `5`.
- `filters`: optional retrieval constraints.
- `stream`: whether streaming output is requested.
- `retrieval_mode`: `vector`, `bm25`, or `hybrid`; defaults to `hybrid`.

The public ChatRequest does not expose structural routing in P0. Query planning
internally derives `navigation_mode` (`direct`, `hierarchical`, or `hybrid`) and
passes non-direct values to `search_documents` or `search_library` only when
`HIERARCHICAL_NAVIGATION_ENABLED=true`. This keeps retrieval backend selection
and document/section navigation as separate contracts.

## ChatResponse

```json
{
  "trace_id": "trace-xxxxxxxx",
  "status": "success",
  "answer": "Answer content [1]",
  "message": "",
  "citations": []
}
```

The public response remains limited to these five fields in CP2. Iteration
counts and tool traces stay in Agent logs and internal run summaries until a
separate Web contract revision approves an optional `run` field.

The Agent's Direct-only versus Direct+Wiki route and `WIKI_CONTEXT_TOP_K` are
internal runtime details. They do not add fields to `ChatRequest`,
`ChatResponse`, or citations. Wiki navigation metadata cannot populate citation
fields; only accepted original Evidence can do so.

## Citation Fields

- `citation_id`: citation number starting from `1`.
- `title`: document title.
- `source_url`: optional source link.
- `doc_id`: document identifier.
- `chunk_id`: stable chunk identifier in
  `{doc_id}_chunk_{zero_based_index}` form. Agent normalizes the legacy
  `{doc_id}::chunk_{index}` Tool Layer form before returning it to Web.
- `score`: retrieval score.
- `snippet`: document excerpt, defaulting to the first 120 characters of
  `chunk_text`.

## Status Values

- `success`：成功。
- `clarification_required`：问题存在歧义，`message` 中返回 Agent 的澄清问题。
- `agent_limit_reached`：达到最大迭代数或重复工具调用阈值后安全停止。
- `tool_error`：非检索工具不存在、参数无效或执行失败。
- `invalid_query`：问题为空或无效。
- `no_relevant_context`：知识库没有足够上下文。
- `retrieval_error`：检索服务异常。
- `llm_error`：模型服务异常。

- `success`: request completed successfully.
- `clarification_required`: the query is ambiguous; `message` contains the
  Agent's clarification question.
- `agent_limit_reached`: execution stopped safely after reaching an iteration
  or repeated-call limit.
- `tool_error`: a non-retrieval tool is missing, receives invalid arguments, or
  fails during execution.
- `unsupported`: the request is outside the current capability boundary.
- `invalid_query`: the query is empty or invalid.
- `no_relevant_context`: the knowledge base contains insufficient context.
- `retrieval_error`: the retrieval service failed.
- `llm_error`: the model service failed.

## Error Response

```json
{
  "trace_id": "trace-xxxxxxxx",
  "status": "invalid_query",
  "answer": "",
  "message": "Please enter a valid question.",
  "citations": []
}
```

## Web Handling

- For `status == success`, display `answer` and `citations`.
- For `status == clarification_required`, display `message` and allow the user
  to reply under the same `session_id`.
- For other non-success statuses, display `message` and do not display the empty
  `answer`.
- Include `trace_id` in logs and issue reports.
- Match citation markers such as `[1]` and `[2]` by `citation_id`.

Models may emit duplicate parallel calls in one response. Agent deduplicates
semantically identical calls within that response; the repeated-call limit is
reserved for an identical call repeated across model turns.

## CP2 Conversation Rules

- Web must pass the same `session_id` throughout one conversation when
  multi-turn context is enabled.
- An empty `session_id` produces a stateless single-turn request.
- Current memory is short-term, in-process Agent memory and is not shared across
  restarts or multiple workers.
- Agent public response fields remain unchanged. Iteration counts and tool
  traces stay in internal Agent run summaries and logs.

### Browser integration regression (2026-10-05)

The Fast streaming route calls the current `SearchTool.search(query, top_k,
mode, filters, trace_id)` contract. It forwards the intersection of requested
sources and the user's authorized document IDs, preserves an explicitly empty
allowlist, and skips retrieval when knowledge base retrieval is disabled.
English questions request English answers and titles. Both streaming modes
clarify an unspecified latest architecture before calling the model.

Research conversation commands accept English `approve` and `cancel` as well
as the existing Chinese commands. Follow-up generation uses the job's report
language; a model service failure is reported separately from insufficient
frozen evidence. Frontend research conversations and response actions allocate
message sequence numbers atomically, so the question, report, favorites and
history can be restored after reload.

The 2026-10-06 browser pilot additionally checks that English fallback titles
use the query directly, without a second model request delaying the SSE done
event. Frontend report citations preserve the prose after inline markers;
chat edit/regenerate uses the message ID in the route and chatId in the body.

### Answer-quality regression (2026-10-06)

Fast streaming now uses bounded retrieval planning for complex questions,
discovers candidate documents through `find_documents` within the hard source
filters, and prefers module/period title matches for each comparison target.
Evidence from targets is interleaved and deduplicated (at most 20 chunks), so
one target cannot consume the whole context. Explicit empty scopes and user
authorization remain authoritative. English titles are generated separately
from the streamed answer to avoid exposing TITLE metadata.

Research follow-ups receive the existing report plus its frozen excerpts;
report references and arithmetic can be resolved without adding new sources.
Citation numbers must belong to the actual report citation set, including
non-contiguous numbering. An unspecified latest architecture returns only a
scope clarification with degraded quality status, without raw candidate history.
English synthesis rejects Chinese narrative and marks failed synthesis degraded
instead of granting complete quality to a raw fallback. The evaluation rubric
also checks exact module/period numbers and unsupported causal/readiness claims;
workflow completion and model scores do not replace factual acceptance.
Historical limitations are labeled by date; later status remains unverified
unless newer evidence confirms it. The frontend persists the streamed RAG tool
output with the assistant text, and renders citations as inline components,
preserving source access after reload.
Short discovered documents are read completely through `get_document` when
they fit within eight chunks, retaining limitations below the top search hits.
Report synthesis uses the same proxy-aware requests transport as regular QA,
retries transient connection failures once, and does not retry deterministic
HTTP rejection. Dated source snapshots without a shared explicit fact scope
are not treated as simultaneous numeric conflicts; same-date conflicts remain
detectable. Follow-up context also includes the original research question.
Before publishing a model-written report, a separate model call audits each
cited claim against the frozen excerpts and checks coverage of the requested
facts. It distinguishes proposed work from completed work and historical
limitations from current ones. A failing audit permits one bounded local repair and
re-audit; persistent defects, malformed verdicts or unavailable validation
produce a degraded English retry notice instead of publishing the unchecked
draft. This adds one general audit call; completion/pending/persistent-status
claims receive a focused status audit when the general audit passes. A local
repair is followed by the same checks, so validation can add up to five calls;
the same configured provider and model are used without expanding source scope.
Grounding repair uses validated JSON edits targeting numbered factual paragraphs
or unique legacy substrings, preserving the rest of the draft; it cannot rewrite
the full report or headings. At most two local repairs are attempted, and each
patched draft must pass structural and grounding checks again.
The audit permits faithful paraphrase, ordinary typo normalization, arithmetic
and comparisons scoped by period/component; it flags material factual defects
rather than requiring every deduction to occur verbatim in a source. Literal
technical IDs and file paths remain exact constraints.
Structural validation also rejects answers to explicit change-calculation
requests that omit numerical differences. Compact retry prompts retain the
same scope and planned-versus-completed constraints as the initial prompt.
English reports use three concise sections (summary, evidence/analysis,
limitations/uncertainty), avoiding compulsory conflict sections that encourage
unrequested expansion. Chinese reports retain their existing five sections.
Qwen report/audit/follow-up requests use the provider-compatible
`enable_thinking` boolean, normally defaulting to false for evidence synthesis.
An explicit enabled thinking mode or payload override is preserved; unrelated
model requests receive no extra provider parameter.
Qwen3 quality audits use bounded reasoning (`thinking_budget=1024`) unless
thinking is explicitly disabled. Qwen Flash synthesis/repair uses a 2048-token
reasoning budget and quality audits use 4096; the response limit reserves room
for the final content as well as reasoning. Explicit disabled mode is respected.

English comparisons explicitly asking to compare dates select short, exact
earlier/later source statements instead of freely inferring current capability
gaps. Selection validates citation identity, snapshot ordering and literal source
content, allowing whitespace-only differences. Event dates in document titles
are distinguished from snapshot dates; later repair actions stay planned work.
An unverifiable selection returns a degraded report, not an unchecked draft.
For English Fast comparisons asking for remaining limitations/constraints,
citations and reasoning can stream while answer tokens are buffered until
quality validation completes. Long-document hits retain snapshot dates even
when their full content exceeds the bounded read window. `Citation.version`
remains an integer version; the snapshot date is internal retrieval metadata.
If validation fails, `done.status` is `quality_validation_failed` and the visible
English response explains that the comparison needs review. No failed draft is
stored as the conversation answer.
Conversation events retain their existing 500-character progress summary in
`message` and additionally persist the full user/assistant body in
`payload.content`. The interaction response also returns the complete answer.
Conversation rendering/copying uses `payload.content`, falling back to `message`
for older events. Long answers and questions no longer fail event validation.
Legacy oversized conversation rows committed before validation are read with
the same summary/body split, so an earlier failed request cannot prevent job
history from loading and its saved answer remains accessible.

### English evidence validation (2026-10-07)

Fast answers to recorded-goal-status and Python-file questions are also buffered
until evidence validation completes. A blank Current Status cell is reported as
`not recorded`; repeated goal IDs are bound to the goal name in the same row.
Table headers in another frozen chunk may supply the column schema, including
headers immediately following `Source excerpt:`. Python-file lists exclude
non-Python paths. Failed validation uses the existing
`quality_validation_failed` status and publishes only the review message.

For multi-document narrative research, the first verified read per selected
document preserves its ranked discussion/action-item locator. Canonical opening
chunks take priority for lifetime/sprint-aggregate questions; a missing selected
document can receive an explicit bounded `source_scope_read` observation.
Search results remain observations until an original read verifies the evidence.
The manifest allowlist, candidate limit and task action budget still apply.

Same-release, same-effective-time enabled/disabled records remain a conflict
even when their export dates differ. Reports quote both records, remain
`degraded`, and request authoritative evidence rather than selecting a winner.
Bounded JSON calls on Qwen/DeepSeek use `enable_thinking=false` by default;
an explicit enabled setting is preserved. Translation-only Qwen-MT models do
not support this project's system-message research contract.

Fast streaming retries transport failures only before any answer content has
been emitted. An empty completed stream is treated as a transport failure.
After two empty streams, the same model may supply a non-streaming answer;
the existing evidence validation still applies. A partial answer is never
concatenated with a retry. HTTP quota failures are not rescued by this path.

2026-10-08: A malformed binary grounding confirmation receives one bounded
retry against the same candidate and actual source; only a JSON boolean is
accepted. Goal-status summaries are also checked against their own explicit
table when they state a Finished count out of the table's total. These checks
do not replace source grounding or infer blank goal statuses.

The shared runtime client also defaults compatible Qwen3, Qwen Flash/Turbo
and DeepSeek calls to non-thinking mode when no thinking preference is set.
This covers Fast answers that reuse the main client because the model IDs
match. Explicit client and global enabled preferences remain honored.

English scope comparisons may include the logical distinction between the
complete system and its narrower component, without adding delivery facts.
The full system cannot inherit a component goal's recorded status. Missing
audit quotations are checked against the real cited source, not accepted as
proof by themselves. Citation checks strip heading lines without discarding
adjacent factual paragraphs. Uncertain dated comparisons retain verified
pending repair actions and do not present them as completed.

Unambiguous literal goal-status claims may be verified directly against the
actual cited goal row. Duplicate IDs require a matching goal name, and blank
statuses remain not recorded. Candidate report tables are never source proof.
After two local grounding repairs fail, synthesis may make one fresh report
attempt using the same frozen evidence. Both structural and grounding checks
must pass before this replacement is published; otherwise the report degrades.

Combined feature-plus-fix minima cannot be rewritten as feature-only minima.
Goal-status paragraphs must cite an excerpt containing the supporting status
row. Unqualified repeated goal IDs remain separate named rows. Goal ledgers
are derived from the supplied frozen table, without inferring empty statuses.
Literal lifecycle aggregate claims can be verified without a semantic model
when the module key matches, the complete sprint summary sums to the stated
lifetime total, and any activity count or busiest-sprint maximum agrees.
Malformed audit citation numbers are recovered only from a unique exact
quotation in an actual source; invented or ambiguous quotations are rejected.

If two anchored audit responses are malformed, one independent full-source
verification may return a strict JSON boolean. False remains a quality defect;
string booleans, malformed output and truncation fail closed. Deterministic
domain checks still apply before this verification.
Invalid local edits preserve the candidate for bounded fresh recovery instead
of being treated as successful corrections. Sprint comparison tables may gain
multiple citations only when every column matches its module's complete source
summary and every row value matches. Conflicting summaries and wrong cells
remain unsupported.

English status-only questions use the actual named goal rows, preserving
duplicate identifiers and empty status cells. The model translates names only;
it cannot provide the recorded status. Lifecycle comparisons can join metadata
and complete sprint tables across chunks of the same document, with citations
to both parts. Conflicting summaries, cross-document joins and wrong arithmetic
remain unsupported. Fast lifecycle answers pass this validation before tokens
are published. Research summary retrieval considers the original objective even
when the planner rephrases its task questions.

Compound Deep Research capability reviews keep literal meeting observations,
recorded goal states and pending action items in separate sections. A finished
goal is not evidence that its implementation was demonstrated. English source
passages with truncated leading words are omitted from these sections. Original
reads include two adjacent chunks on each side, with overlap removed, to retain
whole observations and tables at chunk boundaries.

Complete Skills System exclusions and narrower registry/skill goal rows have
separate source citations. A requested target week is copied from the goal row
and labelled as planning, never completion. Planners preserve a combined
feature-plus-fix minimum; plans that convert it into a feature-only minimum are
rejected. Arithmetic in reports and follow-up answers uses plain readable text.

The Web report export route is `GET /api/research/download?researchId=...`.
It requires a session and ownership of the registered research conversation,
then forwards the same user identity and a server-held Agent token to the
persisted report endpoint. It returns a private, non-cacheable Markdown
attachment with a sanitized filename. The browser receives no Agent token.

Sprint comparisons cite each period's own recorded module counts and both
sources for arithmetic differences. Master module statuses are copied from the
overview table; summed module attribution is separate from unique project
commits. Requested commit identities use the matching module and sprint, without
substituting a Master project total. Missing operational SLA measurements mean
unknown, never failed SLA or zero incidents. Recorded Confluence URLs identify
original sources but do not establish live external accessibility. Fast and
research answers retain that limitation. Fallback plan acceptance targets remain
within the schema limit even when source titles are long, and persisted plans
must validate when read back.

The 2026-10-08 repeat evaluation additionally requires canonical header reads
for total-commit comparisons, rather than counting chronology entries. Fast
answer validation preserves each citation's original URL and read locator.
The locator denotes the verified read anchor and may include adjacent context;
it does not assert the first occurrence of a commit. A latest-delivery question
restricted to one weekly report explicitly states that later sprints cannot
be confirmed. Provider quota failures during buffered validation are surfaced
as provider errors rather than answer-quality rejection.

Evaluation continuation follows explicit case/group/repetition coordinates.
Changing a model does not restart completed tests. The benchmark's optional
`--completed-coordinates` JSON list skips completed coordinates, preserves their
original provenance, and writes only newly executed run envelopes. Reports
identify the actual model per run; a cross-model continuation is not labelled
as a same-model repeat benchmark. Only failed or repair-affected coordinates
require targeted reruns. Missing quality judgments can be completed against
saved real answers without repeating product calls.
