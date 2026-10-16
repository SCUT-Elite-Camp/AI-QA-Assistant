# Selection UI verification — 2026-10-12

## Changes

- Selection toolbar and chat menus use consistent neutral surfaces, Lucide icons,
  compact spacing and rounded corners. The toolbar sits below the selection.
- Chat menu labels distinguish adding to an existing topic and creating a topic.
  Chat titles reserve space for the actions button; keyboard focus reveals it.
- Selection Q&A has a compact quote, one short empty-state prompt, an 80 px
  multiline input, send/stop controls, and responsive full-panel presentation.
  Quick navigation is hidden while the drawer is open. Message actions retain
  only Copy; citation Reader remains in the message content.
- Follow-ups reuse the server-owned temporary chat. Save copies only persisted
  message IDs supplied by the server, excluding failed requests/client contents.
- Fixed a MemoryResponsePolicy parameter mismatch encountered with persistent
  Memory enabled. Fact expiry uses the coordinator's request visibility cutoff.

## Evidence

The running local launcher enables `PERSISTENT_MEMORY_ENABLED=true`; no secrets
or runtime data were added to Git. Real Agent/model, BFF session/CSRF and native
Confluence access were used for the browser checks.

- At 1440 × 900, the drawer input measured 362 × 80 px with its bottom inside
  the viewport. At 700 × 900 it measured 618 × 80 px and remained visible.
- Shift+Enter inserted a newline; Enter and the Send button submitted questions.
- Asked “Explain the role of the Agent layer in two sentences”, then “Summarize
  your previous answer in one short sentence”. Both returned actual answers.
- Save navigated to `/chat/1e3f5ec7-d62f-4a05-b3c5-aefb6f852709`; refreshing
  retained both questions and answers, including source citations. This saved
  fixture predates the English title change and keeps its original title.
- Frontend: 51 suites / 267 tests passed; Vue typecheck and production build
  passed. Focused tests cover server chat reuse, persisted IDs, failed-message
  exclusion, IME/newline input, duplicate submission and cancellation.
- Agent: 16 MemoryResponsePolicy tests passed. Full pytest remains blocked at
  collection by existing imports of removed `InMemoryConversationMemory` in
  `test_chat_research_boundary.py` and `test_cp2_orchestration.py`.

This is UI/runtime verification, not a new machine-quality or holdout score.
The first real response described historical single-turn scope from its sources;
its accuracy against current architecture was not independently accepted here.
The selection endpoint delivers its checked final response after completion;
this change does not add provider-token streaming to that endpoint.
