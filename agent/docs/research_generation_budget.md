# Research generation budgets

Research Planner and report generation use the configured Thinking model and the
same proxy-aware requests transport. Browser/session identity, frozen source
scope, native permission and version/hash checks remain unchanged.
Coordinator planning receives the full catalogue's readable titles, numbers and
versions; complete source IDs/hash bindings remain server-side in the manifest.

| Setting | Default | Meaning |
| --- | --- | --- |
| `RESEARCH_MODEL_REASONING_TOKENS` | 3072 | Additional completion reserve for reasoning |
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
