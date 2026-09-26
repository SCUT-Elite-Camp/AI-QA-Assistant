# Evidence-grounded Wiki

## Purpose

The Wiki is an offline-compiled navigation layer. It helps the Agent discover related concepts, entities, pages, document versions, Sections, and Evidence. It is never a citation authority; final answers must cite original Evidence.

## Production flow

```text
Document + Section + Evidence
  -> document-scope Entity/Concept candidates
  -> exact Candidate-to-Evidence binding
  -> evidence-aware Wiki page promotion
  -> conservative same-kind identity resolution
  -> bounded taxonomy planning
  -> Summary/Entity/Concept/Index page compilation
  -> Claim audit -> bounded repair -> re-audit
  -> atomic revision publication
```

Online exploration is explicit:

```text
Direct Evidence -> coverage gap
  -> wiki_search -> wiki_read_page -> wiki_read_sources
  -> wiki_search_evidence -> Evidence Gate -> Citation Validation
```

## Safety and lifecycle

- `WIKI_INGEST_ENABLED=false` and `KNOWLEDGE_NAVIGATION_ENABLED=false` by default.
- Personal and enterprise scopes are isolated by owner and knowledge-base identity.
- Every published claim has `document_version_id`, `section_id`, `evidence_id`, exact quote offsets, and Evidence hash.
- Unsupported claims receive at most two repair attempts. Every audit verdict and every REWRITE/DROP transition is persisted as an immutable event; remaining failures block the new revision.
- Publication is atomic. Page title, slug, type, content, and claim provenance are revision-scoped, so saving a failed draft cannot alter the previous published revision.
- Exact-input reruns reuse the published revision without model calls; unchanged document candidates and page inputs are cached.
- Every complete schema-valid model response is cached by the full request hash. Failed or truncated responses are never cached, so an interrupted offline build resumes without treating partial output as knowledge.

## Evaluation labels

Meeting Record runs are `PROBE` until the frozen manual quality audit and retrieval evaluation pass. Production enablement additionally requires the non-meeting generality suite and the frozen 48-query evaluation. Runnable code or an AI-only audit is not production acceptance.

## Reviewed-cohort retrieval signal

The full reviewed-release PROBE used all 48 content pages as one question per page,
211 original Evidence chunks, and 96 paired retrieval-and-answer records. A local
Qwen2.5-14B-Instruct-AWQ generator and Ragas 0.4.3 judge scored every record
without execution errors. Wiki-guided retrieval increased mean Ragas context
precision from 0.3855 to 0.4387; the paired 95% bootstrap interval for the
0.0532 difference was 0.0283 to 0.0778. Mean answer correctness changed from
0.2517 to 0.3048, and faithfulness from 0.7291 to 0.7658; both paired
intervals included zero.

This is evidence of a useful retrieval-candidate signal in the reviewed cohort,
with limited evidence for answer-quality improvement. Questions, reference
answers, and reference Evidence IDs were derived from those same Wiki pages;
the guided arm was an offline candidate pool rather than the production Agent
policy. The generator and judge used the same local model. The independent
human-labeled Gate D and production Milvus latency remain `NOT_RUN`; the
release decision remains `PARTIAL`, and navigation/publishing flags stay off.
The reproducible runner and Ragas scoring code are under `eval/wiki/`; run
outputs remain local and are excluded from Git.
