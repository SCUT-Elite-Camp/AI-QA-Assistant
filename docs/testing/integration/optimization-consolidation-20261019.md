# Optimization consolidation review

Date: 2026-10-19. Delivery branch: `optimization`. This review consolidates the
completed Thinking-loop and Deep Research harness changes in the shared checkout.
It is implementation/regression evidence, not a new answer-quality acceptance score.
Historical datasets, scores and failed provider attempts remain unchanged.

## Resulting behavior

- Thinking starts one bounded native-tool Agent loop from the original question.
  Exact claim/source binding and local MiniCheck gate release; rejected candidates
  return to that same allowance. The removed intent, rewrite, routing and repair
  sub-pipelines are not fallback execution paths.
- Deep Research plans over the complete authorized catalogue, waits for approval
  of the current plan version/hash, then runs parallel explorers, coordinator
  synthesis, independent review, bounded fresh repair agents and final approval.
  Old sequential workers, rule verifiers, fallback reports and executable UI mocks
  are removed. Historical outputs are retained without relabeling old reviews.
- Explicit loopback Research development mode grants all catalogue files to
  enabled signed-in users. Production retains native/local permissions. Identity,
  ownership, source version/hash and report release binding remain enforced.

## Additional review fixes

1. Failed explorer prerequisites now block every descendant before scheduling.
   A newly blocked prerequisite cannot accidentally unlock its dependent agent.
2. Reviewer input includes the complete exact Markdown, including headings, as
   well as indexed editable blocks and fresh originals. The persisted review is
   still bound to the exact revision/hash.
3. Re-entering review after repair keeps the completed repair visible while the
   current review is running. A linear timeline no longer resets that stage to
   pending during the loop.
4. Online and offline MiniCheck require the selected model's `verified.json`,
   repository identity and weight hash. Transformers is explicitly pinned to the
   hashed `pytorch_model.bin` or `model.safetensors` format, so another file in the
   same directory cannot silently replace the verified checkpoint.

## Validation

| Check | Result | Private evidence |
| --- | --- | --- |
| Full Agent suite | 639 passed; two dependency deprecation warnings | `D:/AI-QA-Assistant/optimization-final-tests-20261019.xml` |
| Frontend suite | 318 passed in 61 files | `D:/AI-QA-Assistant/optimization-frontend-tests-20261019.log` |
| Frontend type check | `vue-tsc -p tsconfig.app.json --noEmit` passed | Command result |
| Frontend production build | Passed with an external fresh SQLite DB/output directory | `D:/AI-QA-Assistant/optimization-review-build-20261019.log` |
| Root evaluator regression | 2 passed in `eval/test_agent_latency_ab.py` | Command result |
| Real local MiniCheck smoke | Supported liveness claim accepted, contradictory readiness claim rejected | `D:/AI-QA-Assistant/optimization-minicheck-smoke-20261019.json` |

The full Agent result includes Research, Chat, source permission, lineage, Memory,
budget and verification tests; targeted reruns are not added as distinct cases.
Tests of removed components were retired with those components. Production
boundaries are exercised using controlled model/transport dependencies in the
automated suite. The two synthetic real classifier cases validate the loader and
inference only; they are not an accuracy estimate or a real-source acceptance run.

The earlier full-suite collection failure while Chat was being independently
modified is resolved by this combined run. No real Groq/BFF/Milvus end-to-end
acceptance or repeat-stability claim is made here. The recorded provider daily
quota failure and remaining live-protocol coverage are retained in the
[Thinking implementation report](../quality/thinking-agent-loop-20261019.md).
Research live acceptance remains pending as described in its
[architecture](../../../agent/docs/research_team_architecture.md).

Runtime databases, source exports, credentials, model weights and build outputs
remain outside the commit. This delivery updates `optimization` only and does
not merge `dev` or change the separate PR58 checkout.
