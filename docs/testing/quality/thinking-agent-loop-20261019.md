# Thinking Agent loop implementation and verification

Date: 2026-10-19. This is implementation evidence, not a new answer-quality
acceptance score. Previous evaluations and frozen reports are unchanged.

## Implemented behavior

- The first Thinking request sends the original question, verified history,
  trusted scope and permitted native tool schemas. No intent, rewriting,
  clarification, planning or completeness model runs beforehand.
- The Prompt owns those decisions. Source tools and three registered native
  controls (`prepare_answer`, `ask_clarification`, `report_insufficient`) share
  one model-call budget. The final grounded generation uses the same model with
  tools closed. This avoids mixing native calls with a content control protocol.
- Exact claim/source binding precedes local MiniCheck. Unconfirmed assertions
  return privately to the same loop for more evidence or regeneration; every
  replacement is bound and verified again. No rejected candidate is released.
- Default limits are 10 model calls, 8 tool attempts, 48 claim checks, 180 seconds,
  30000 serialized context characters and 150000 conservative reserved tokens.
  Failed attempts count. No separate title call, provider retry or fallback model
  escapes the allowance. Token reservation is not exact provider usage accounting.
- Source pools retain full bodies and lineage privately. Model views include
  complete bodies once with reference locators, or whole excerpts when a body
  exceeds the allowance; metadata and navigation are bounded too.
- Old intent classifiers/routers, preparation/clarification/rewrite modules,
  completeness/repair workflow, Wiki Chat controller and question-specific
  report/keyword answer generator are removed. Their implementation-only tests
  and classifier/cascade evaluation executors are retired. Public QueryPlan DTOs
  remain; their old semantic hints no longer dispatch execution. Offline fact
  coverage metrics and frozen historical datasets/reports remain useful.
- Fast retains original-query fixed tools and a single generation, with binding
  validation. MiniCheck regeneration belongs to Thinking only.

Configuration and release details: [current mode contract](../../../agent/docs/chat_mode_contract.md).

## Automated verification

- From `agent/`, `python -m pytest -q --tb=short`: **632 passed**, 2 dependency
  deprecation warnings, 32.31 seconds. Temporary files and JUnit output reside
  outside the checkout.
- Root quality-evaluator regression subset: **12 passed**. These cover the
  retained offline metrics/dataset selection, not model answer quality.
- After the final English-fixture/legacy private-hint and benchmark-manifest
  cleanup, the affected **81 Agent regressions passed** again. This subset is
  not added to the full-suite count as distinct tests.
- English new-loop cases cover original first input, native tool/control
  separation, model-selected rewritten queries, catalog plus batch full reads,
  exact quote repair, MiniCheck rejection/unverified feedback, regeneration,
  exhausted budgets, unavailable inference, repeated/forged actions, required
  source/file evidence, deadlines and bounded context.
- JSON/SSE integration uses the production source guard with controlled native
  transports/model/classifier. A rejected first candidate stays private; only
  the verified replacement is released. Source changes during verification stop
  release. Existing permission, lineage, Memory and Fast tests remain in the run.
  Controlled boundaries are not real BFF/native-source acceptance.

Private test artifact: `D:/AI-QA-Assistant/thinking-loop-20261019/pytest-delivery.xml`.

## Real MiniCheck inference

The actual local `lytang/MiniCheck-DeBERTa-v3-Large` weights were loaded, including
the installation manifest/hash check. A synthetic English source distinguishes
liveness from retrieval readiness. MiniCheck accepted its supported liveness
assertion and rejected its contradictory retrieval-readiness assertion.

This is **2 classifier smoke cases**, not a benchmark or an accuracy estimate.
It does not establish atomicity, completeness, general semantic correctness or
the absence of false acceptance. Existing MiniCheck error analyses still apply.

Private artifact: `D:/AI-QA-Assistant/thinking-loop-20261019/minicheck-smoke.json`.

## Real answer-provider attempt and remaining coverage

A direct Agent request reused the seen English Local Setup question and its
frozen project sources in an isolated runtime/database, with current native
permissions. The configured model remained Groq GPT-OSS-120B/high.

The first real request selected `get_document` and completed an authorized full
read. The next request was rejected with `tool_use_failed`: the provider encoded
the former JSON control content as a nonexistent function named `JSON`. Its
counted recovery request then hit the provider's 200000-token daily allowance
(`429`). All three HTTP attempts consumed the same budget; one source tool ran,
no claim verification occurred, and the response was `llm_error` with no answer.
No embedding/Milvus search was exercised because the model chose a direct read.

The JSON control protocol was subsequently replaced with registered native
controls and `tool_choice=required`; controlled loop/transport tests verify the
new wire payload and behavior. **A complete real knowledge-answer regeneration
run on this final protocol remains unverified because of provider quota.**
No alternate provider, fake answer or external judge was used to claim success.
This is not full Web/BFF/session/parser acceptance, unseen quality measurement
or repeat-stability evidence.

The initial real attempt, immutable request copies and responses are retained
privately at `D:/AI-QA-Assistant/thinking-loop-20261019/live-smoke.json`; source
bodies, credentials, runtime databases and model weights are not committed.
