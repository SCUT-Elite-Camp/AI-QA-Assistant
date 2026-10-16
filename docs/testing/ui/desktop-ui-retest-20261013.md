# Desktop UI retest — 2026-10-13

## Changes verified in the real browser

- Home and chat keep the original capsule for short, single-line input.
- Naturally wrapped text and explicit newlines expand the text above the controls. Shortening or clearing restores the capsule. Deep Research alone does not expand it.
- Selection Copy and Ask icons anchor their top-left corner 2 pixels right and 2 pixels below the last selected line's bottom-right corner. Viewport bounds keep the toolbar on screen. Composer button positions remain unchanged.
- The retrieval sidebar header button now uses the same neutral ghost button defaults as Share, Admin and Theme: 32px control size, 20px icon, 6px padding and 6px radius. Opening and closing the sidebar were verified in the browser.
- The Ask icon opens Selection Q&A with the selected word. Copy shows a success toast, but the automation clipboard API returned an empty value; this retest does not claim clipboard contents were verified.

Runtime and screenshots are outside the checkout in `C:/Users/Hola/.codex/tmp/aiqa-ui-20261012`. The latest Web build is `build-navbar-unified`; screenshots include `navbar-unified-20261013.png`, `selection-corner-20261013.png`, `desktop-capsule-20261013.png`, and `desktop-expanded-20261013.png`.

## Automated gates

| Gate | Result | External log |
| --- | --- | --- |
| Agent full pytest | 945 passed; two dependency deprecation warnings | `release-agent-final6.log` |
| Frontend full tests | 56 suites, 291 tests passed | `push-frontend-final.log` |
| Final frontend type check | Passed | `release-types-navbar-unified.log` |
| Final production build | Passed | `release-build-navbar-unified.log` |
| Milvus timeout tests | 21 passed | `release-milvus-timeout.log` |

The final frontend full suite was rerun after the positional, observer and header button refinements and passed all 291 tests. The final build, type check and live browser verification also passed. This is a desktop retest, not mobile acceptance.

## Runtime recovery and quality limits

Original Milvus collections stalled while loading after shutdown. A separate acceptance cluster on loopback port 19539 was populated from the unchanged 74 current document projections using the actual 384-dimensional embedding model: 702 chunks and 572 sections. Original volumes and collections were preserved. Collection loads now have a bounded timeout, configured by `MILVUS_LOAD_TIMEOUT_SECONDS` (default 10 seconds).

The real Gemini research run `research-985a8f3eac924f84ac39ed5d18d39d23` completed 4/4 tasks in 157.8 seconds, with 16 actions and nine documents read. It generated an English report with citations, but still marks some checkpoint and meeting comparisons as conflicts. Treat its quality as requiring review. Earlier research failures remain in history; repeated repair-informed questions are not frozen holdouts or evidence of repeat stability.

Selection model answering, standalone Save, research download/full Reader, Personal Library and remaining quality coverage are not newly accepted by this UI retest. Historical July reports and scores were not edited. No production release or merge is claimed.
