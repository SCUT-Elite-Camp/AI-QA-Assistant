# CP2 Deep Research A-side evaluation pack

This directory is the frozen, reviewable input owned by side A. It does not run
the three experiment groups or apply the side-B Page Index/link fixes.

## Frozen scope

- 18 cases, all grounded in the local `RAG` Confluence snapshot.
- One immutable SourceManifest per case. The manifest is the allowlist; a
  `forbidden_document_ids` list supplies explicit permission-leak probes.
- The same question, manifest hash, model parameters, and permission scope must
  be copied into G1/G2/G3 run records.
- Six evaluation layers: Plan, Retrieval, Evidence, Report, Citation, Runtime.
- Deterministic hard gates always take precedence over model-judge scores.

The source JSON under `data-persistence/data/documents` is intentionally not
committed because it contains internal content. The committed manifests retain
document identity, Confluence version, URL, and content hash. Validation fails
if the local source snapshot drifts.

## Commands

Run from the repository root:

```powershell
python eval/deep_research_a/suite.py validate
python eval/deep_research_a/suite.py preflight
python eval/deep_research_a/suite.py preflight --require-all-groups
python eval/deep_research_a/suite.py score path/to/run-record.json
python eval/deep_research_a/suite.py batch-score path/to/records --output-dir eval/reports/cp2-dr-v1
```

`preflight --require-all-groups` is deliberately strict. On the current `dev`
snapshot it reports G2/G3 unavailable because `agent/deep_research` is not in
that branch. The frozen implementation reference is recorded in
`config/frozen_baseline.json`; side B must merge or check out that capability
before executing G2/G3.

To refresh the source snapshot after an intentional Confluence update:

```powershell
python eval/deep_research_a/suite.py freeze --write
python eval/deep_research_a/suite.py validate
```

Review the diff. A freeze is a dataset version change and must not be mixed into
an existing experiment batch.

`batch-score` enforces all 162 coordinates (18 cases x 3 groups x 3 repeats),
checks cross-group invariants, scores every retained failure, and emits
`results.csv`, `scores.jsonl`, and `summary.json`. Use `--allow-incomplete` only
for an explicitly labelled dry run.

## Run-record contract

Each raw run is one JSON object conforming to
`schemas/run_record.schema.json`. Never discard failed runs. Provider changes,
fallbacks, retries, recovery attempts, terminal status, failure stage, and error
code are mandatory runtime data.

The model judge receives only the question, the frozen source excerpts, and the
candidate report. Its JSON result conforms to `schemas/judge_output.schema.json`.
It cannot override permission, hash, locator, citation-presence, or link checks.

## Result comparison

Copy one row per run into `templates/g1_g2_g3_results.csv`. Aggregate only after
all three groups have the same `case_id`, question hash, manifest hash, model
configuration hash, and repeat count. A completed workflow is not automatically
a passing workflow.
