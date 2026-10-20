# Independent answer protocol V4 and actual rerun (2026-10-20)

## Change

The final answer model now returns required `answer` plus private `claims` in the
same generation. Claims copy exact body substrings; the server resolves original
character offsets and rejects overlaps, missing claim text and uncovered prose,
numbers, citations or meaningful symbols. Whitespace/basic layout punctuation can
remain between spans. Repeated identical text binds every occurrence. The original
answer layout/order is preserved, with missing citation markers inserted at span
ends. The old claims-only envelope is rejected. Abstention requires both empty
answer and empty claims. Fast still uses one generation; Thinking still runs
MiniCheck after binding and may regenerate within its existing budget.

No HTTP/SSE private metadata was added, and native source permissions, provenance,
version/hash checks and rejected-draft release boundaries are retained.

## Verification

- Agent `python -m pytest`: **673 passed**, two dependency deprecation warnings.
- Includes independent body layout/order, mismatch, uncovered facts/symbols,
  overlapping/repeated claims, old-envelope rejection, explicit abstention,
  character offsets and buffered SSE release. Unicode capability is named explicitly.
- `git diff --check` passed.

## Actual request

One actual Thinking request used the same temporary `deepseek-v4.1-flash` gateway
model and frozen English EN-Q21 regression:

> Who completed Multi-Query Fusion, on which date, and with how many queries?

The source is the native-authorized version 6 of Preliminary Ideas. Its table row
records Completed, Jiaxing Dai / July 30, and at most three parallel queries.
Neither a year nor the historical wrong Fast answer was sent as a gold fact.
Production environment files were unchanged; credentials and hidden reasoning
were not persisted. The old V3 run is retained unchanged in its separate directory.

## Observed result

Final status **success**, complete provenance, unchanged source and frozen code.
Seven model calls, two real tools (`search_documents`, `get_document`), three
verification rounds / nine classified claims. Total elapsed **119.344 seconds**.
The source retrieval used the actual local embedding/Milvus/reranking path; this
remains a direct Agent run, not BFF/session/CSRF/Reader or full product acceptance.

1. The first answer contained four claims; exact binding passed. MiniCheck rejected
   the compound completion/owner/date claim and accepted the other three.
2. The second answer contained three claims; exact binding passed. MiniCheck rejected
   the fragment `by Jiaxing Dai on July 30.` and accepted the other two.
3. The final answer contained two claims; exact binding and MiniCheck both passed.
   Only this accepted body was released, with citations inserted.

Codex source review finds the first rejected compound assertion supported by the
row and its header: a per-case false rejection. The second rejected fragment lacks
its own subject, although its body context supplies one. The final first claim
still combines completion, owner and date despite the atomic-claim instruction.
The binding validator checks coverage/integrity, not semantic atomicity. These
observations illustrate MiniCheck sensitivity to wording and claim boundaries;
this one seen case is not a general quality or stability result. No external judge
was used and no holdout score is claimed.

## Final actual model package

The following is the actual final model JSON, before server citation insertion.

```json
{
  "answer": "Multi-Query Fusion was completed by Jiaxing Dai on July 30. Multi-Query Fusion generates or uses at most three queries for parallel retrieval.",
  "claims": [
    {
      "text": "Multi-Query Fusion was completed by Jiaxing Dai on July 30.",
      "supports": [
        {
          "citation_id": 1,
          "quote": "Multi-Query Fusion | Completed | Jiaxing Dai / July 30"
        }
      ]
    },
    {
      "text": "Multi-Query Fusion generates or uses at most three queries for parallel retrieval.",
      "supports": [
        {
          "citation_id": 1,
          "quote": "generate or use at most three queries for parallel retrieval"
        }
      ]
    }
  ]
}
```

## Private artifacts

`D:/AI-QA-Assistant/thinking-temporary-model-20261020/run-20261020-152319/`
contains final-model-package.json, all model requests/native actions/factual drafts,
real tool inputs/results, binding/source spans and MiniCheck verdicts for each
round, execution events, final response, protocol/source/code/weight hashes,
mechanical audit and Codex per-case review. Hidden reasoning and API secrets are
excluded. The artifact manifest hashes files for review.
