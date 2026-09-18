"""Exercise the durable worker on a copied frozen-cohort PROBE database."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for dependency in (ROOT, ROOT / "data-pipeline", ROOT / "data-persistence"):
    sys.path.insert(0, str(dependency))

from pipeline.confluence_snapshot import discover_confluence_snapshots  # noqa: E402
from pipeline.wiki.cache import CachingJsonCompletionClient  # noqa: E402
from pipeline.wiki.confluence_source import load_authoritative_confluence_document  # noqa: E402
from pipeline.wiki.domain import WikiScope  # noqa: E402
from pipeline.wiki.extraction import CandidateExtractor, CandidatePromotionSelector  # noqa: E402
from pipeline.wiki.identity import IdentityResolver  # noqa: E402
from pipeline.wiki.job import WikiBuildConfig, WikiBuildService  # noqa: E402
from pipeline.wiki.llm import DeepSeekJsonLLM, deepseek_api_key_from_environment  # noqa: E402
from pipeline.wiki.page import WikiPageCompiler  # noqa: E402
from pipeline.wiki.quality import WikiQualityGate  # noqa: E402
from pipeline.wiki.queue import WikiLifecycleCoordinator  # noqa: E402
from pipeline.wiki.source import document_to_wiki_source  # noqa: E402
from pipeline.wiki.taxonomy import TaxonomyPlanner  # noqa: E402
from pipeline.wiki.worker import WikiStageWorker  # noqa: E402
from storage.wiki_store import WikiStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("confluence_root", type=Path)
    parser.add_argument("--cohort", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    if not (args.run_dir / "wiki.sqlite3").is_file():
        raise FileNotFoundError("copy the frozen PROBE SQLite database before running worker probe")
    cohort = json.loads(args.cohort.read_text(encoding="utf-8-sig"))
    snapshots = {item.identity: item for item in
                 discover_confluence_snapshots(args.confluence_root, require_storage=True)}
    scope = WikiScope(source_scope="enterprise", knowledge_base_id=cohort["space_id"])
    documents = []
    for item in cohort["pages"]:
        snapshot = snapshots[tuple(item["identity"])]
        if (snapshot.content_sha256 != item["content_sha256"] or
                snapshot.source_content_sha256 != item["source_content_sha256"]):
            raise ValueError("frozen Wiki worker source changed")
        documents.append(document_to_wiki_source(
            load_authoritative_confluence_document(snapshot), scope,
        ))
    store = WikiStore(args.run_dir / "wiki.sqlite3")
    api = DeepSeekJsonLLM(api_key=deepseek_api_key_from_environment())
    cache = CachingJsonCompletionClient(api, store)
    service = WikiBuildService(
        repository=store, extractor=CandidateExtractor(cache),
        promotion_selector=CandidatePromotionSelector(cache),
        identity_resolver=IdentityResolver(cache), taxonomy_planner=TaxonomyPlanner(cache),
        page_compiler=WikiPageCompiler(cache),
        quality_gate=WikiQualityGate(cache, cache, max_repair_rounds=2),
        config=WikiBuildConfig(enabled=True, publish=False),
    )
    lifecycle = WikiLifecycleCoordinator(store)
    for document in documents:
        lifecycle.document_ingested(document)
    jobs = lifecycle.schedule(debounce_seconds=0, publish=False)
    if len(jobs) != 1:
        raise ValueError("frozen Wiki worker changes were not coalesced into one job")
    worker = WikiStageWorker(service, lambda lease: documents, worker_id="cohort-probe")
    for _ in range(8):
        if not worker.run_once():
            raise RuntimeError("Wiki worker stopped before completing all stages")
    with store.connection() as db:
        row = db.execute("SELECT status,payload FROM wiki_jobs WHERE job_id=?", (jobs[0],)).fetchone()
        state = json.loads(row["payload"])
        run = db.execute("SELECT status FROM wiki_build_runs WHERE revision=?",
                         (state["revision"],)).fetchone()
        page_count = db.execute("SELECT COUNT(*) FROM wiki_page_revisions WHERE revision=?",
                                (state["revision"],)).fetchone()[0]
    manifest = {
        "evaluation_label": "PROBE", "cohort_sha256": hashlib.sha256(args.cohort.read_bytes()).hexdigest(),
        "source_pages": len(documents), "jobs": len(jobs), "job_status": row["status"],
        "revision": state["revision"], "revision_status": run["status"],
        "pages": page_count, "cache_hits": cache.cache_hits, "api_misses": cache.cache_misses,
        "published": False, "human_review": "NOT_RUN", "formal_retrieval_evaluation": "NOT_RUN",
    }
    (args.run_dir / "worker-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
