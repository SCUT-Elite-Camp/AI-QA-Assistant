# Knowledge navigation integration boundary

Retrieval Evidence is authoritative. Section trees, Wiki pages, and any optional graph are navigation metadata and cannot be cited as answer sources.

## Ownership

| Layer | Production owner | Responsibility |
| --- | --- | --- |
| Document and Section | `models/document.py`, `pipeline/structure.py` | Stable document versions, Section paths, and Evidence membership. |
| Semantic Wiki chunks | `pipeline/wiki/chunker.py` | Structure-aware non-overlapping knowledge chunks with exact Evidence spans. |
| Wiki source contract | `pipeline/wiki/source.py` | Active-version, scope, hash, Section, and Evidence validation. |
| Candidate extraction | `pipeline/wiki/extraction.py` | Document-scope Entity/Concept extraction followed by exact Evidence binding. |
| Identity and taxonomy | `pipeline/wiki/identity.py`, `pipeline/wiki/taxonomy.py` | Conservative same-kind identity resolution, stable slugs, and bounded folders. |
| Page compilation and quality | `pipeline/wiki/page.py`, `pipeline/wiki/quality.py` | Source-bound pages, Claim audit, bounded repair, and re-audit. |
| Build lifecycle | `pipeline/wiki/job.py` | Incremental cache reuse, draft assembly, and publication gating. |
| Wiki persistence | `storage/wiki_store.py` | Scope-separated revisions, atomic publication, FTS search, and source resolution. |
| Agent tools | `tool_layer/wiki_tool.py` | Wiki discovery/read tools and `wiki_search_evidence`, which reruns normal Evidence retrieval in Wiki-linked documents. |
| Agent coverage | `agent/exploration/coverage.py`, `agent/runtime/runner.py` | Direct retrieval first; explicit exploration only after a measured coverage gap. |

Tests use fake model/store backends under each service's `tests/` directory. Private cohort selection, DeepSeek probes, review exports, and retrieval experiments live under `eval/wiki/` and write only to Git-ignored run directories.

## Online flow

Public Evidence search remains Direct-only. When the coverage assessor finds a cross-document knowledge gap, the Agent may use:

```text
wiki_search
  -> wiki_read_page
  -> wiki_read_sources
  -> wiki_search_evidence
  -> Evidence Gate and Citation Validation
```

The first three calls provide navigation priors only. `wiki_search_evidence`
resolves the authorized Wiki page/claim to source document IDs and invokes the
same BM25/vector Evidence retriever used by Direct search within that scope.
No automatic Direct/Wiki score fusion is performed.

## Feature gates and rollout

- `WIKI_INGEST_ENABLED=false` prevents production ingestion unless explicitly enabled by an offline build entry.
- `KNOWLEDGE_NAVIGATION_ENABLED=false` prevents Toolset registration of Wiki exploration tools.
- `AGENTIC_EXPLORATION_ENABLED=false` preserves the original Direct retrieval path.

A passing AI audit is not formal acceptance. Meeting Record output remains a `PROBE` until the frozen manual quality audit is complete. Production enablement additionally requires the non-meeting generality suite and frozen retrieval comparison defined in the implementation plan.

Section IDs and heading paths remain provenance metadata inside Wiki source
records. The former standalone Section retrieval and PageIndex subsystems are
not part of the active production path.
