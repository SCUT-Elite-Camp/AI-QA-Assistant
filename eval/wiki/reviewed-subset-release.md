# Human-reviewed Wiki subset release

The verified six-table human review is the input to `publish_reviewed_subset.py`.
The command checks the frozen review against the source database, then creates a
new revision in a **separate SQLite database**. The original DRAFT is retained.

Selection is conservative. A page is included only when its own worthiness and
summary, every final Claim, any audit/repair event, and its identity's promoted
Candidates all have positive human decisions. An INDEX page is retained only
with at least one content page. Removed pages cannot appear in structural links
or rendered Wiki links. Claim text and Evidence source rows are copied exactly.

```powershell
$env:PYTHONPATH = "$PWD;$PWD/data-persistence;$PWD/data-pipeline"
python -m eval.wiki.publish_reviewed_subset `
  --database eval/wiki/runs/wiki-refactor-strict-audit-12-20260917/wiki.sqlite3 `
  --bundle eval/wiki/runs/wiki-refactor-strict-audit-12-20260917/review-bundle-v6 `
  --archive eval/wiki/runs/wiki-refactor-strict-audit-12-20260917/gate-c-full-human-submission-20260917.zip `
  --provenance eval/wiki/runs/wiki-refactor-strict-audit-12-20260917/gate-c-full-submission-provenance-20260917.json `
  --output-db eval/wiki/runs/wiki-reviewed-release-20260918/wiki-verified.sqlite3 `
  --report eval/wiki/runs/wiki-reviewed-release-20260918/report-verified.json `
  --activate
```

`--activate` changes only the separate output database. Without it, the new
revision remains DRAFT for inspection. The command refuses to overwrite either
the database or report. The output is an offline release candidate, not a
production deployment. No production Wiki DB or deployment target is configured
in this checkout, and the navigation, ingest and publish flags remain off.

## Current verified result (2026-09-18)

- Source DRAFT: `wr_95886d6fc38a1ded1dd8128d`.
- New revision: `wr_review_4b893706ac816c9ddfb3b6c7`.
- Retained: 49 pages including INDEX, 458 final Claims, 36 identities and 40
  promoted Candidates. Excluded: 26 pages including the original FAILED pages.
- Every retained page and Claim has a positive human verdict. Claim text and
  source ID sets equal the source DRAFT; retained pages have no dead links.
- The exact release revision was indexed with local BGE-M3 in the isolated
  database: 49 vectors; a query returned 5 Wiki pages. This is an integration
  smoke check, not Gate D or a production latency measurement.
- Local automated suite: 508 passed, 2 skipped. Web: 73 passed and typecheck
  passed. An earlier full Python run failed one Office preview test because the
  Windows temporary path was too long; it passed with a short temporary path.
- Gate A local automation: PASS. Source Gate B: PROBE PASS. The filtered
  revision has a subset consistency check, but the full frozen-cohort Gate B
  has **NOT_RUN** on this revision. Gate C stays **PARTIAL** under the recorded
  owner waiver. Gate D stays **NOT_RUN** under the same waiver.
- Production visibility: **NOT_RUN**. The output has not been copied to a
  production DB, indexed in production, deployed or exposed to users.

Before production activation, use a versioned backup of the active Wiki DB,
verify scope and active document versions, index this exact revision for the
Wiki vector backend, and run the production serving and rollback checks. Any
subsequent generated or edited content requires its own review or exclusion.
