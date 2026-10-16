# Confluence RAG Space English Translation

Date: 2026-10-14. Scope: all current documents visible to the configured native account in the RAG space.

The current 74-page catalogue was inspected. Seventeen pages contained Chinese titles or prose and were translated to English. The final native API readback found no Chinese text nodes or display attributes across all 74 current pages. The User Guide's translated draft was also published to the current version.

Twenty-one of 24 document attachments were translated and updated under their original attachment IDs: 14 PowerPoint files, 3 Markdown files, 1 PDF, 1 Excel workbook, and 2 images. The remaining two PDFs and one JSON attachment were already English. The space avatar is outside the document inventory. Every changed attachment was downloaded again and its SHA256 matched the uploaded English file.

Existing document structure, tables, media relationships, code interfaces, historical numbers, and dates were retained. Chinese personal names were transliterated; actual historical filesystem paths, font identifiers, CJK regular-expression ranges, and code punctuation remain technical identifiers. English versions of historical screenshots are labelled as translations. PowerPoint files were rendered and reopened in Microsoft PowerPoint; the PDF was rendered; native Excel verified the historical totals of 20 executed, 20 passed, 0 failed, and 100% passing. Historical report results are not new acceptance scores.

Backups, version-aware write evidence, English attachments, readback audits, and the refreshed source mirror are saved outside the checkout at `D:/AIQA/confluence-english-20261014/`. Credentials and raw source exports must not be committed.

The ordinary Confluence export, attachment download, parsing, chunking, embedding, Milvus, and BM25 pipeline is used for local synchronization. Completion and index reconciliation are recorded in that directory's `translation-state.json` and `reconciliation-report.json`.

The exporter detected 76 supported files requiring ingestion. Seventeen pages changed version; 57 page storage/normalized hashes changed. An unchanged-version example gained `confluence-local-id` anchor comments without a prose change. These source/locator changes are retained and reindexed under the existing lineage checks, rather than treated as new answer-quality evidence.

The pretranslation English evaluation cohort remains preserved at `D:/AIQA/fast-optimization-20261014/english/`. Its frozen source versions and hashes are invalidated by this content migration; it must not be resumed against translated documents or have its old scores relabelled. A subsequent evaluation requires a separate source/code freeze. No Groq generation calls are required for translation or local synchronization.

Final verification passed: 74 page records plus 24 attachment records; 95 parsed/indexed documents; 1,167 Evidence and BM25 chunks; 756 section records; actual embedding/collection dimension 384. Vector text and BM25 source/chunk keys match the current document projections, with no duplicate visible vectors or pending ingestion. The three unsupported binary/JSON attachments remain explicitly unindexed, with current source metadata. All 98 records passed native access checks and were returned by the Agent catalogue API. Seventeen translated page exports were checked against live storage hashes and versions after draft synchronization; all matched.

Retained drafts and live-document bodies were also checked and translated where needed, preserving current published content. Confluence's localized macro descriptions and Excel-generated locale metadata are application UI strings, rather than authored Chinese prose. Nine English retrieval smoke probes across Vector, BM25, and Hybrid returned valid current chunks. These are synchronization/runtime checks, not a new answer-quality acceptance run.
