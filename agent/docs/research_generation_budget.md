# Research generation budgets

Research Planner and report generation use the configured Thinking model and the
same proxy-aware requests transport. Browser/session identity, frozen source
scope, native permission and version/hash checks remain unchanged.
Coordinator planning receives the full catalogue's readable titles, numbers and
versions; complete source IDs/hash bindings remain server-side in the manifest.

| Setting | Default | Meaning |
| --- | --- | --- |
| `RESEARCH_MODEL_REASONING_TOKENS` | 3072 | Additional completion reserve for reasoning |
| `RESEARCH_REVIEW_REASONING_TOKENS` | Inherits `RESEARCH_MODEL_REASONING_TOKENS` (3072) | Separate Reviewer reserve; increase explicitly for long audits without inflating every explorer call |
| `RESEARCH_MODEL_TIMEOUT_SECONDS` | 180 | Bounded model HTTP timeout for planning and execution; runtime deadline and total token reservations still apply |
| `RESEARCH_REPORT_THINKING` | true | Reasoning for report writing/staged sections; false requests brief non-reasoning synthesis, without changing explorer/reviewer reasoning or review gates |
| `RESEARCH_CONTROL_THINKING` | true | Reasoning for Reviewer/final coordinator JSON; false retains all checks but requests non-reasoning control output |
| `RESEARCH_MODEL_OUTPUT_TOKENS` | 2048 | Maximum visible-output target per call |
| `RESEARCH_MODEL_TOTAL_TOKENS` | 64000 | Planning limit; approved coordinator execution's shared durable completion-token cap |
| `RESEARCH_MODEL_MAX_RETRY_WAIT_SECONDS` | 60 | Maximum permitted rate-limit retry delay |

Each call receives an explicit completion cap equal to its visible-output target
(capped by OUTPUT_TOKENS) plus its reasoning reserve. The prompt explains both
targets. These reasoning/output targets are advisory: GPT-OSS exposes a combined
`max_completion_tokens`, not a hard split between reasoning and visible output.
The configured reasoning effort remains unchanged. Explicitly disabled reasoning
on other supported models does not spend a reasoning reserve.

For example, the main report request targets 2048 visible tokens plus 3072
reasoning tokens (5120 total). A staged section targets 768 plus 3072 (3840).
This avoids treating the old 2500-token combined cap as 2500 visible tokens.
Input tokens and provider context/TPM limits remain separate constraints.
DeepSeek-compatible calls translate the thinking switch to native `thinking.type`;
Qwen-style `enable_thinking` is not assumed to control DeepSeek reasoning. A
provider without a true off switch (for example GPT-OSS) may still reason within
the combined cap. Read observations carry evidence identities rather than a
second copy of the original already supplied in the evidence list; synthesis
receives exact verified quotes once, in the findings, plus citation metadata.

On `finish_reason=length`, empty visible output, or provider HTTP 413, the whole-report path switches
to section generation instead of immediately repeating the full draft. English
generates Evidence and analysis, then Summary, then Limitations and uncertainty;
Chinese uses the existing five sections. Every section receives the original
frozen evidence and citation numbers. Prior drafts are explicitly untrusted,
never additional evidence or authorization. Incomplete sections are rejected.
Assembly is deterministic; there is no final rewrite that can truncate the
completed sections. The assembled draft still needs structural/citation checks,
independent Reviewer approval and the coordinator's final release check. An
incomplete draft fails the job without publishing a fallback report.

Calls reserve their full completion cap before transport; successful usage
reconciles that reservation, while missing usage and ambiguous transport failures
retain it. 429/413 rejection releases its completion reservation. Nested helpers
and parallel agents share a thread-safe ContextVar budget rather than resetting it.

For new `execution_mode=coordinator` Plans, `budget.max_tokens` covers the entire
approved execution: explorers, coordinator synthesis, Reviewer, fresh repair
agents, staged generation and final release check. SQLite reservations in
`research_model_usage` survive process restarts; recovery cannot replenish the
quota. Planning uses a separate preapproval limit. The runtime creates this
additive Research table automatically; no Web migration is required.

Explorers and repair agents receive the remaining shared completion budget,
remaining decision count and an explicit `must_finish` flag on every turn. The
last approved decision, exhausted tool allowance, or low remaining tokens switches
the prompt and allowed actions to `finish` only: summarize verified evidence and
state uncovered criteria as gaps. A final-turn search/read is rejected before any
tool execution. This does not invent findings from snippets or skip review.
With at most 12,000 tokens remaining, explorer/repair JSON targets 1,024 visible
tokens (still capped by OUTPUT_TOKENS); final coordinator JSON targets 512.
Reviewer JSON has a 4,096-token visible target (capped by OUTPUT_TOKENS), allowing
reasoning and compact actionable issues without forcing a tiny verdict call.
For plans at or below 12,000 tokens, explorers are prompted for at most two short
findings and synthesis receives a 300-word target. These are prompt/output
allocations, not permission to skip criteria: uncovered aspects remain explicit.
An invalid finding is omitted individually without discarding other verified
findings; a result with only invalid findings cannot pass as supported evidence.
Reports describe evidence gaps rather than citing documents for internal errors.

Exploration retains up to half the execution allowance, capped at the combined
configured synthesis, review and final-coordination call caps. Repair retains up
to a third, capped at the configured review and final-coordination calls. Reservations
enforce this headroom atomically across parallel agents; current in-flight
reservations count against the remaining balance. These are allocations inside
the existing approved token limit, not extra tokens. A small allocation cannot
guarantee completion if no supported evidence is obtained or review still fails.

Invalid/missing chunk locators and invalid/empty line ranges are returned as
bounded `tool_error` observations to explorers/repair agents, while the attempted
call still consumes a tool action. Agents must copy returned chunk locators or
use explicit `line:start-end` ranges, never bare document IDs. Authorization,
source version/hash, cancellation and hard budget failures remain terminal.
Persisted task/job errors keep safe stable codes rather than arbitrary provider
messages; full tool errors are not exposed as source text or secrets.

For an explicitly finalizing decision, the transport can shrink its normal call
cap to the actual unreserved balance (minimum 128 tokens) and tells the model to
close with concise structured results. Thinking remains enabled. This avoids
rejecting a brief verdict merely because its normal maximum exceeds the balance;
it does not add tokens, refund unknown usage, or release malformed/unreviewed text.
Future-role headroom also leaves space for the current agent's closing call.

A Reviewer may use a separately configured reasoning reserve. If an audit reaches
`length` after producing draft reasoning but no complete verdict, one bounded
second stage retains the complete original/report inputs and asks for the JSON
verdict using that draft analysis as untrusted context. Both stages keep the
configured thinking mode and share the same durable execution budget. Only a
complete verdict passing all existing citation/block/hash checks is accepted.
Revised drafts include prior review notes to check the corrections efficiently;
these notes never replace fresh original reads or authorize a new revision.
Review checks semantic support, not exact terminology, and treats conditional
gap criteria as conditional rather than requiring canned negative claims.

Known `type=json_object` / object-valued `content` response-format envelopes are
unwrapped before strict role/plan validation. A findings/edits-only object can
represent a finish response, but cannot invent evidence or authorize tools.
Truncated/invalid explorer JSON gets bounded feedback within the same approved
decision/token allowance; failed model outputs are persisted as charged decisions.
Already persisted finish decisions can replay after interruption without another
model/tool call. Later terminal outcomes use new immutable entity IDs; snapshots
show the latest outcome per agent while protected traces retain prior failures.

Only references with exact quotes in verified originals survive finding binding;
unquoted or invalid extra references are pruned rather than turning into citations.
If no valid quoted reference survives, the finding is rejected and the model can
correct it within its remaining decisions. The independent Reviewer still checks
semantic support for the entire statement, not just substring matches.

The old legacy runtime and its per-attempt quota are removed. Saved legacy plans
and reports remain historical data; interrupted legacy jobs require a new job
and human approval, rather than resuming through the retired graph.
See [team architecture](research_team_architecture.md) for the additive API fields,
tool/time limits, independent review gates and recovery assumptions.

429 handling permits one transport retry after the provider's numeric Retry-After
or `try again in ...s` delay (with a small margin), bounded by the configured wait.
Other HTTP rejections are not transport-retried. Current source access is checked
before waits, before every attempt and after successful responses. Longer delays
fail closed rather than being replaced by an immediate retry. Existing bounded
report recovery paths share the same completion budget. Exhausted token budgets,
incomplete staged sections and terminal HTTP 413/429 stop execution without
publishing a report. They do not restart the removed whole-report rescue/fallback
path after a staged failure or immediately send another request into a rate limit.

Logs include model, completion cap, attempt, actual completion/reasoning usage,
finish reason, remaining budget and section progress. They exclude source text,
request prompts and authentication material. Token exhaustion never turns an
unfinished section into a completed report.

Focused regression tests: `python -m pytest tests/unit/test_research_model_budget.py
tests/unit/test_research_model_access.py tests/integration/test_research_team.py`.
