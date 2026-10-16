# Stream presentation retest — 2026-10-12

## Changes

- Main chat buffers checked preview deltas and paints Unicode graphemes on
  animation frames, with adaptive speed and a maximum of four per frame.
- Final verified text replaces the queued draft before canonical SDK text
  arrives. Presentation continues after persistence without a sudden full-text
  jump. Controls remain in the responding state until the queue finishes.
- Stop, failure and unmount cancel queued paints. A committed final answer can
  be revealed immediately using Stop. Differing quality-repair suffixes replace
  queued draft text; transient previews are not saved.
- New prose gains contrast over 420 ms, without blur or movement. Each renderer
  owns character birth times; Markdown reparses preserve animation progress.
  Recent wrappers are bounded to 96 graphemes. Code and citation widgets retain
  their normal rendering. Reduced-motion preferences disable the effect.

## Verification

- Frontend: 53 suites / 282 tests passed. Vue typecheck and production build
  passed. Build used an isolated database and an output directory outside the
  checkout.
- Focused tests cover burst/frame limits, Unicode, cancellation, stale callbacks,
  final repair and commit ordering, history rendering, animation age, bounded
  wrappers and preservation of code/citation structures.
- Real browser test used the configured OpenRouter Fast model through the
  existing session/CSRF BFF at
  `/chat/d9cbf6ef-8958-4efd-bba5-70a8eeb211e6`. The Chinese copying question
  beginning “渐显效果验证” returned a complete answer ending “验证结束。”
- A 16-second DOM observation recorded 161 samples and 99 text changes. Early
  lengths grew 1, 4, 10, 16, 22 rather than whole paragraphs. Rendered glyph
  opacity included approximately 0.19, 0.71 and 0.98 during the fade. Samples
  and a screenshot are stored outside the checkout in the local test directory.
- On completion, Stop disappeared and normal message actions returned. Refresh
  preserved the same full answer; historical messages had no animation wrappers.

This is presentation/runtime verification, not new answer-quality acceptance.
Fast, Auto and Thinking share the main-chat presentation code; this round's
real model test used Fast. Selection Q&A and Research do not gain new provider
streaming from this change. Existing source permission and lineage checks remain
in force.
