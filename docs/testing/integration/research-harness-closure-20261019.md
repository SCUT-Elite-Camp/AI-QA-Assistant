# Research harness finalization and reasoning validation

Date: 2026-10-19 (Asia/Shanghai). Base: `44a78f3` on `optimization`.

The revised harness completed a real model execution with thinking enabled for
every role. This establishes runtime closure, not general answer-quality or
production-permission acceptance. Codex's separate per-case review still finds
coverage and wording defects in the released example.

## Changes

- Explorers/repair agents receive remaining tokens, remaining decisions and an
  explicit finalization instruction. Their last decision submits supported
  findings/edits and evidence gaps; it cannot spend another tool call.
- Atomic shared reservations retain budget for synthesis/review/release. As the
  balance shrinks, headroom leaves room for the current closing call. Finalizing
  requests may use a smaller remaining cap, with thinking preserved, rather than
  failing solely because their normal maximum is larger than the balance.
- Chunk/line locator syntax is explicit. Recoverable locator/range errors return
  counted tool-error observations. Permission, source drift and hard-limit
  failures remain terminal.
- Known provider JSON envelopes normalize before strict role/plan validation.
  Truncated/invalid explorer output receives bounded feedback, and failed outputs
  still count as decisions. Finish replay does not repeat completed model calls.
- Later agent outcomes use additional immutable records. Progress shows the
  latest result per agent; protected traces retain failed outcomes.
- A finding keeps only exact quoted bindings to verified originals. Unquoted
  extra references are pruned; entirely unbound findings are rejected. This is
  binding validation, not a substitute for semantic review.
- DeepSeek thinking uses native `thinking.type`. Default report/control reasoning
  remains enabled through the global settings. Reviewer reasoning can have its
  own allowance; planning/execution transport timeout is configurable.
- A truncated Reviewer audit can continue once into a structured-verdict stage
  with complete original/report inputs and untrusted draft audit notes. Revised
  reports carry prior review notes, without replacing fresh source checks.

Configuration and limits: [generation budgets](../../../agent/docs/research_generation_budget.md).

## Successful real execution

Private artifacts: `D:/AI-QA-Assistant/research-team-quality-20261019/`.
Job: `research-4d4cb4f19e134cffa73ecfe9860c1e52`.

The question/tasks/criteria reuse the unchanged previously human-approved,
model-generated plan over the same 98-file catalogue. The user subsequently
authorized fixes, reruns and more reasoning budget. This success is an execution
regression of that frozen plan, not a newly unseen planning/quality holdout.
The original actual planning call and its human approval remain in the first
attempt's evidence. No generic/mock planner fallback generated the final report.

| Item | Observed result |
| --- | --- |
| Temporary model | `deepseek-v4.1-flash`, resolved `deepseek-v4-1-flash-260910` |
| Execution ceiling | 48,000 completion tokens, including reasoning |
| Reviewer combined call ceiling | 12,288; 8,192 reasoning reserve is a target, not an independent provider hard split |
| Other role caps | Explorer 3,648; synthesis 4,096; final coordinator 2,560 |
| Model calls | 9; all native thinking enabled; no transport errors |
| Reported input | 21,121 tokens |
| Reported completion | 13,387 tokens, including 10,844 reasoning tokens |
| Exploration | Two parallel explorers succeeded, with 10 findings |
| Review/release | Revision 1 passed; coordinator approved; BFF report GET returned HTTP 200 |
| Report status | `degraded` for evidence gaps, independently of `review_status=passed` |
| Evidence checks | Two citation source versions/hashes, all exact finding quotes and reviewed report hash validated |
| Review coverage | Both used citations and all five factual blocks checked |
| Length | 350 whitespace-separated body words including citation markers, excluding Markdown headings |

The run used real BFF session/CSRF, production Research coordinator/tools, local
384-dimensional embedding, Milvus hybrid retrieval and reranking. Authorization
used the explicitly requested loopback development full-catalogue policy. This
does **not** establish native ACL-denial behavior. Existing parsed projections
were read; no fresh ingestion/parser acceptance, browser layout acceptance or
repeat-stability claim is made.

The successful case needed no repair. Earlier real attempts separately exercised
Reviewer rejection, fresh repair agents, two revisions and staged audit verdicts;
those attempts were not released when final review/budget checks failed. Successful
repair-to-release and interruption recovery are also covered by isolated tests.

## Separate Codex content review

Review version: `codex-case-review-v1`, following the
[evaluation policy](../quality/evaluation-policy.md). No external grading API was
called. The product Reviewer is part of the system under test, not an offline
judge. Codex review is not an independent human review.

| Dimension | Score (0–4) |
| --- | --- |
| Correctness | 3 |
| Completeness | 3 |
| Source faithfulness | 3 |
| Citation quality | 3 |

Weighted diagnostic score: **75/100; policy quality acceptance not met**.
Core candidate-evidence, authorization, source-drift and dependency descriptions
are mostly supported and the report scopes them as documentation rather than
deployment proof. Remaining issues:

- Reader's specific permission/body-version/hash/excerpt validation is not
  explicitly covered; some source-access conditions are grouped rather than
  exhaustively listed.
- “No ranking/selection rule beyond RRF” is broader than justified: the source
  also describes a Top-K policy and excerpt/coverage checks. Missing exact
  weights, tie-breaking or score semantics would be narrower wording.
- Absence of a formal definition should not imply absence of the concrete
  citation-validation behavior described by the source.

These are unresolved quality issues, not a claim that model review proves every
assertion. The fixture is repair-informed; no scores or historical outcomes were
rewritten to relabel it as unseen or production accepted.

## Validation and complete cost accounting

Agent full suite: **662 passed**, two existing dependency deprecation warnings.
The changes do not edit frontend code; no new frontend/UI acceptance is claimed.

All failed attempts, including runner setup mistakes and two additional unapproved
planning calls, are retained outside the checkout. Known completion usage for the
entire temporary-model debugging series is **88,774 tokens**, including the two
small probes. Known input usage is **256,770 tokens**. Three ambiguous transport
failures additionally retain **10,944 completion tokens** as conservative quota
reservations; unknown input/billing cannot be inferred from successful usage.
This cumulative debugging usage is separate from the successful run's 13,387.
No currency amount is claimed without provider billing records.

The private artifacts include `verification.json`, `codex-case-review.json`,
`all-attempts-usage.json`, exact report/plan, role/model traces and HTTP receipts.
Temporary credentials were not written into repository configuration or reports.
The owned temporary services were stopped after verification; original indexes,
collections and volumes were preserved.
