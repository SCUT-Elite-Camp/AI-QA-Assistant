# Natural answer presentation and assertion marking (2026-10-20)

## Correction

Protocol V5 requires a natural answer first, then factual assertion extraction.
Multi-aspect answers use separate Markdown bullets and line breaks, with optional
brief introductions and labels. It no longer forces the answer into a sequence
of rigid subject/predicate verification statements. Fast and Thinking answer
Prompts both include the presentation requirement. The UI underlines assertions
at normal font weight; nonfactual introductory/presentation prose and inter-claim
spacing remain unmarked. Exact body spans, original quote checks, citation remapping,
source-native permission/version/hash checks and rejected-answer buffering remain.
No extra model request was added to Fast.

## Claim completeness limitation

V4's full-character coverage rule forced every word, including headings and
connective prose, into a claim. V5 removes that rule. Every declared claim still
must match a real answer substring and valid source fragment, with no overlapping
claims or unbound citation markers. However, factual assertion extraction is a
model obligation, not proven by string alignment. The private binding report
explicitly records `claim_completeness=model_selected_not_verified`. A model can
omit a factual assertion; MiniCheck only checks declared assertions. This is a
material limitation, not a claim that presentation prose is semantically verified.

## Verification

- Agent: **632 passed**, two existing dependency warnings.
- Frontend: **280 passed / 58 files**; negative probes and jsdom CSS warnings remain.
- Vue TypeScript check: passed.
- Production build and disposable database migration: passed, isolated under
  `D:/AI-QA-Assistant/natural-answer-20261020/build-check/`.
- `git diff --check`: passed.
- Tests cover normal lead-ins/bullet labels outside assertions, exact spans,
  uncovered citation rejection, truthful completeness reporting, and Markdown
  rendering without clickable whitespace fragments.

## Actual browser observation

A real English Fast request in the current signed-in browser used the previously
authorized temporary `deepseek-v4.1-flash` model because the configured default
model had returned unavailable in the preceding demo. Credentials/default environment
files were not changed; only the running development Agent process uses that model.
The actual retrieval, native source checks, BFF session/CSRF path and durable saved
message were used. This is not a Thinking/MiniCheck acceptance run.

The question asked who completed Multi-Query Fusion, its completion date and the
parallel-query limit. The saved model answer has an ordinary introduction and
three bullets for owner, date and queries. Its introduction is not annotated.
The answer preserves July 30 without inventing a year; an explicit source-year
qualification appears. The actual quote/source dialog remains functional.
This verifies presentation for one seen example, not repeat stability or overall
answer/claim-extraction quality. An earlier demo request was interrupted by the
development page reloading during the production build; it is not counted as a pass.

Private local evidence:
- `D:/AI-QA-Assistant/natural-answer-20261020/actual-browser-answer.json`
- `D:/AI-QA-Assistant/natural-answer-20261020/browser-demo/natural-answer.png`

Historical V3/V4 reports and scores remain unchanged.


## Follow-up: hide redundant citation markers

At the user's request, Chat answers with valid claim metadata no longer render
numbered citation badges. Underlined assertions retain quote/title/Reader access.
Only known source markers outside code are hidden at render time; stored body,
source bindings, offsets and access checks are unchanged. Legacy messages without
valid assertions keep their citation controls, and Research retains its behavior.

Frontend **281 passed / 58 files**, Vue type check and isolated production build
passed. Actual browser verification confirmed the badges are gone from the saved
claim-linked answer and clicking the owner assertion still opens its quote/source
dialog. No new model request or Agent code change was required for this follow-up.
Screenshot: `D:/AI-QA-Assistant/citation-display-20261020/browser-demo/answer-without-badges.png`.
