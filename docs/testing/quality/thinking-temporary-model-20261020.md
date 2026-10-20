# Temporary-model Thinking regression (2026-10-20)

## Result and scope

The earlier unsupported-year regression did **not** recur in this one run.
The answer correctly identifies Jiaxing Dai, July 30, and at most three queries.
All three claims passed exact binding and actual local MiniCheck; the final
response was `success` with complete provenance.

This does not isolate a model upgrade: model, Prompt, execution path and output
language differ from the historical Fast run. It is one seen regression, not an
unseen holdout, repeat-stability result or general hallucination benchmark.
No verifier rejection occurred, so this run does not test rejection-to-regeneration.

## Model and frozen question

The user supplied a temporary gateway. Its authenticated model catalog returned
only `deepseek-v4.1-flash`; completion responses identify
`deepseek-v4-1-flash-260910`. These are gateway-reported identities; the underlying
weights were not independently verified. No other model/provider was selected.
Standard OpenAI-compatible requests were used without an undocumented vendor
thinking flag. Application mode was `thinking` throughout.

Question, from frozen English `EN-Q21`:

> Who completed Multi-Query Fusion, on which date, and with how many queries?

The previous Fast run used the same English source with a Chinese-answer
instruction and twice added 2023 to July 30. This run uses the existing frozen
English equivalent, not a newly claimed holdout. The source row records:

- Owner: Jiaxing Dai; status: Completed.
- Completion date: July 30, with no year.
- Query allowance: at most three queries for parallel retrieval.

No expected facts, previous wrong answer or special year warning was injected
into the Agent request. Existing production prompts were not tuned for this run.
The source was the project document **Preliminary Ideas**, not an `[Eval KB]`
fixture. Its ID is `009ee0fae8f7d4e3388d937d1b80bd13`, native source version `6`.
The complete source-file SHA-256 matches the previous frozen protocol; exact
code/source hashes are in the private run protocol.

Historical Fast evidence remains unchanged; see
[the original claim-binding report](claim-binding-verification-plan-20261015.md).

## Released answer

```text
Multi-Query Fusion was completed by Jiaxing Dai.[1]

Multi-Query Fusion's completion date is July 30.[1]

Multi-Query Fusion generates or uses at most three queries for parallel retrieval.[1]
```

The single citation resolves to the exact current table chunk. Each paragraph
has its own source quote and exact offsets. The response does not contain a
self-score or private claim/verifier data.

## Observable decisions and tool calls

These are recorded native actions and outcomes, with explanations authored by
Codex. They are not the model's private chain of thought. Returned hidden
reasoning fields were excluded from the saved artifacts and this report.

| Order | Observable action | Result |
| --- | --- | --- |
| 1 | First model request: original question, trusted source scope and six native source/control schemas | No prior classifier, rewriting or retrieval-model request |
| 2 | Model calls `get_document(doc_ids=["009ee0fae8f7d4e3388d937d1b80bd13"])` | Native source checks; one complete document and one source-bound chunk returned |
| 3 | Second model request consumes the source projection; model calls `prepare_answer({})` | Normal native control protocol accepted |
| 4 | Third model request has no tools | Generates three claims and source quotes, without adding a year |
| 5 | Exact binding, then local MiniCheck | Three supported verdicts in one verification round |
| 6 | Current-source and citation checks, then release | `success`, complete provenance, no unchecked candidate released |

The controller used a known, permitted document ID directly. It did not perform
TopK search, catalog browsing or a multi-document batch read. Consequently this
run did not invoke embedding/Milvus or demonstrate the insufficient-TopK expansion
path. The actual get_document tool executed through the production ToolExecutor
and source guard; no fake transport, source evidence, model or classifier was used.

## Runtime and resource observations

| Measurement | Observed |
| --- | ---: |
| Total Agent wall time | 61.500 s |
| Shared loop budget elapsed | 58.671 s |
| Model requests / HTTP attempts | 3 / 3, all HTTP 200 |
| Source tool executions | 1 |
| Sum of model HTTP waits | 10.389 s |
| Source-tool elapsed time | 1.922 s |
| MiniCheck gate stage | 37.797 s |
| Claims / supported verdicts | 3 / 3 |
| Provider prompt / completion tokens | 5139 / 612 |
| Provider-reported total tokens | 5751 |
| Conservative server token reservation | 33563 |
| Failed/repeated/recovery calls | 0 |

The verification stage took about 61% of wall time. It includes initial local
weight/hash/tokenizer setup, classifier work and live source checks; no finer
instrumentation separates these costs. It cannot be reported as classifier
forward latency alone or a steady-state measurement. The remaining wall time
includes authorization checks and orchestration. Server reservation uses the
documented conservative allowance, not the provider's actual token accounting.

The model projection contained one 1988-character complete body, one exact
reference locator, and no repeated excerpt copy. The three serialized model
payloads were 6340, 8866 and 5586 characters. Full raw tool/chunk metadata was
retained privately instead of being repeatedly inserted into model history.

The run stayed within the unchanged default limits: 10 model calls, 8 source
tool attempts, 48 claim checks and 180 seconds. There was no title-generation
request, provider retry, fallback model or hidden auxiliary generation.

## Review and limits

Codex reviewed each returned assertion against the original table row and its
actual quote binding. Correctness, completeness, source fidelity and citation
quality each receive 4/4 under the current rubric, giving this one answer 100.
This is Codex per-case review, not an external judge or independent human review.

Separate findings:

- **Runtime:** completed successfully with the supplied temporary gateway.
- **Machine verification:** real MiniCheck supported 3/3 assertions.
- **Codex source review:** the previous unsupported year was not added; all
  three requested facts were covered without unsupported additions.
- **Architecture:** native control and grounded-answer protocols ran cleanly;
  full-read projection, private binding and checked release worked on this path.
- **Not established:** model-only causality, general quality superiority,
  repeat stability, rejection recovery, catalog/batch expansion, warm inference
  latency or full Web/BFF/session/CSRF/Reader/parser acceptance.

Current native Confluence permissions and normal source checks remained enabled;
Research development mode was false. Runtime/database outputs were isolated
outside the checkout. Original source files, code, indexes and populated
environment files were not changed. The temporary key was held only in the
test process and was not saved in scripts, reports or request artifacts.

## Private artifacts

Directory: `D:/AI-QA-Assistant/thinking-temporary-model-20261020/run-20261020-142425/`.

- `trace-summary.md` / `decision-trace.json`: human-readable and structured
  observable decision/tool chain.
- `model-calls.json`: exact request bodies, native calls, factual answer drafts,
  token usage and timings; credentials/hidden reasoning excluded.
- `tool-calls.json`: real tool arguments, result and source lineage.
- `verification-checks.json`: exact bindings, source offsets and actual verdicts.
- `execution-events.json`: ordered events with request-relative times.
- `protocol.json`: frozen question, configuration and source/code/weight identity.
- `result.json`, `mechanical-audit.json`, `codex-review.v1.json`: final result,
  mechanical checks and distinct source review.
- `artifact-manifest.json`: hashes for the retained JSON/Markdown artifacts.

No private source export, database, credential or model weight is added to the
repository. This report supplements earlier evidence; it does not revise old
scores or turn a previously blocked run into a pass.
