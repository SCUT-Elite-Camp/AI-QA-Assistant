# Version-aware Document/Section Hierarchical Navigation (P0)

## Scope

P0 adds an optional navigation layer to both enterprise knowledge-base search
and Personal Library search. It supports PDF, Markdown, DOCX, and PPTX while
keeping chunk-level Evidence as the only answer and citation authority.

`retrieval_mode` still selects the retrieval backend (`vector`, `bm25`, or
`hybrid`). `navigation_mode` independently selects the path:

- `direct`: legacy chunk retrieval only;
- `hierarchical`: retrieve likely sections, search their Evidence, and retain a
  lower-weight direct-retrieval reserve;
- `hybrid`: rank-fuse direct and section-guided Evidence.

If no reliable section exists, the request falls back to `direct`. A section is
navigation metadata, not citable evidence.

## Ingestion and version boundary

Structure is built after parsing/chunking and before a version becomes ready or
active. Each section stores a deterministic ID, parent/path/level, extractive
summary, page or slide range when available, and the IDs of its Evidence rows.
The section index is derived per `version_id`; retrieval only considers active,
authorized versions.

- Markdown uses heading paths already attached to Evidence locators.
- PDF uses the native table of contents when available; a no-TOC root is marked
  low quality and cannot narrow retrieval.
- DOCX uses heading styles and body-block locators, including table positions.
- PPTX creates one section per slide using its title or a deterministic fallback.

Existing indexed documents without structure remain searchable through the
direct path and can be backfilled by normal re-ingestion.

## Runtime contracts

Enterprise `search_documents` and Personal Library `search_library` accept:

```json
{"navigation_mode": "direct | hierarchical | hybrid"}
```

The Attachment Service endpoint `POST /v1/library/search` also returns:

```json
{
  "navigation": {
    "mode": "direct",
    "requested_mode": "hierarchical",
    "section_hits": 0,
    "scoped_candidates": 0,
    "fallback_reason": "none | no_reliable_sections"
  }
}
```

Set `HIERARCHICAL_NAVIGATION_ENABLED=true` in Agent/Toolset and Attachment
Service processes to enable non-direct modes. The default is `false`; when the
gate is off, services force `direct` while preserving the requested mode in
diagnostics.

## Security and rollback

Owner, knowledge-base, document, active-version, and hard-filter constraints are
resolved before section search. Section hits can only narrow the already
authorized attachment/version set. Rollback requires setting
`HIERARCHICAL_NAVIGATION_ENABLED=false`; section data may remain stored because
the direct path never depends on it.

For rollout, compare direct and hybrid modes on the same frozen query set. Track
answer support/citation validity first, then no-result rate, fallback rate,
section hit rate, and latency. Do not enable by default until the evidence and
latency gates are accepted.
