# Clickable answer claims (2026-10-20)

## Delivered behavior

New Fast/Thinking evidence answers render bound assertions in bold. Clicking or
pressing Enter/Space opens a Supporting evidence dialog containing the original
quote and source document title for every support. Open source document uses the
existing saved-message Reader. The feature survives history reloads, covers
selection Q&A and supports multiple quotes/documents per assertion. Old messages
without bindings retain their existing display; no metadata is invented/backfilled.
Research output without these chat bindings is unchanged.

## Data and boundaries

Agent exposes only `answer_claims`: accepted claim ID, final-body text/Unicode
code point offsets, and quote/citation ID supports. It projects the private binding
onto the final answer after citation normalization/renumbering and checks exact
source identities. Full MiniCheck reports, feedback, verification inputs, raw
reasoning and scores are not exposed. No additional model request is made.

The BFF checks final body slices, nonoverlap, known citation IDs and exact normalized
quote containment before persisting/releasing `data-answer-claims`. Existing local
identity/ownership, source-native permissions, provenance and version/hash release
checks remain in place. Browser-supplied metadata is not used as model evidence.
Saved quotes/titles are snapshots under the user's existing history policy; the
full Reader continues to check current sources. No schema migration is added.

The renderer decorates parsed Markdown text nodes, preserving headings, emphasis,
code, tables, links and citation controls. Invalid/mismatched saved metadata cannot
attach a claim popup to different prose. The display contract uses Unicode code
points to avoid Python/JavaScript UTF-16 offset mismatches. `comark@0.4.0`, already
the renderer's underlying parser, is now an explicit dependency for matching parsed
visible text rather than injecting arbitrary HTML.

## Verification

- Agent: **633 passed**, two dependency deprecation warnings.
- Frontend: **279 passed / 58 files**. Negative database/cleanup probes log their
  expected failures; jsdom also reports a CSS parser warning. All assertions pass.
- `pnpm exec vue-tsc -p tsconfig.app.json --noEmit`: passed.
- `pnpm build`: passed, including migration against a disposable external SQLite
  database and output under `D:/AI-QA-Assistant/claim-display-20261020/build-check/`.
  Existing Rollup annotation/peer/chunk warnings remain. Initial build invocation
  with an empty local authToken failed config validation; the successful isolated
  invocation used a nonsecret local-only placeholder without touching credentials.
- `git diff --check`: passed.
- Actual MessageContent + Comark component tests cover bold rendering, click and
  keyboard activation, multiple quotes/titles, Reader handoff and saved messages.
  Nuxt modal/Reader shells are stubbed in these isolated component tests; this is
  not a full authenticated browser/native-source acceptance run or visual review.
- Integration tests reject forged quotes/current-source denial without durable
  writes or public claim metadata; rejected Thinking drafts remain private.
- Original real EN-Q21 model output was replayed through only the new projection:
  both claims map exactly onto final public body spans and citation identities.
  This reuses prior recorded output, not a new model/permisson acceptance run.
  Artifact: `D:/AI-QA-Assistant/claim-display-20261020/prior-real-answer-display-projection.json`.

The current test counts reflect the working tree including the separately completed
Fact removal; earlier reports/counts are historical and have not been relabeled.
