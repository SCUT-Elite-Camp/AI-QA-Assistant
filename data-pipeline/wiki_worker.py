"""Run the durable enterprise Wiki lifecycle worker against active RAG documents."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for dependency in (ROOT, ROOT / "data-pipeline", ROOT / "data-persistence"):
    sys.path.insert(0, str(dependency))

from pipeline.wiki.cache import CachingJsonCompletionClient  # noqa: E402
from pipeline.wiki.domain import WikiScope  # noqa: E402
from pipeline.wiki.extraction import CandidateExtractor, CandidatePromotionSelector  # noqa: E402
from pipeline.wiki.identity import IdentityResolver  # noqa: E402
from pipeline.wiki.job import WikiBuildConfig, WikiBuildService  # noqa: E402
from pipeline.wiki.lifecycle import WikiDocumentLifecycle, WikiDocumentProjection  # noqa: E402
from pipeline.wiki.llm import DeepSeekJsonLLM, deepseek_api_key_from_environment  # noqa: E402
from pipeline.wiki.page import WikiPageCompiler  # noqa: E402
from pipeline.wiki.quality import WikiQualityGate  # noqa: E402
from pipeline.wiki.search import BgeM3WikiVectorSearch  # noqa: E402
from pipeline.wiki.taxonomy import TaxonomyPlanner  # noqa: E402
from pipeline.wiki.worker import WikiStageWorker  # noqa: E402
from storage.document_store import DOCS_DIR  # noqa: E402
from storage.wiki_store import WikiStore  # noqa: E402
from shared_runtime.wiki_paths import resolve_wiki_db_path  # noqa: E402


def _enabled(name: str) -> bool:
    return os.getenv(name, "false").strip().casefold() in {"1", "true", "yes"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Persistent Wiki ingest worker")
    parser.add_argument("--once", action="store_true", help="Reconcile and drain ready stages once")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--debounce-seconds", type=int, default=5)
    parser.add_argument("--worker-id", default=f"wiki-{os.getpid()}")
    args = parser.parse_args()
    if not _enabled("WIKI_INGEST_ENABLED"):
        raise RuntimeError("WIKI_INGEST_ENABLED is false")
    if args.poll_seconds <= 0 or args.debounce_seconds < 0:
        raise ValueError("Wiki polling and debounce intervals are invalid")
    wiki_path = resolve_wiki_db_path(ROOT)
    store = WikiStore(wiki_path)
    projection = WikiDocumentProjection(
        DOCS_DIR, knowledge_base_id=os.getenv("ENTERPRISE_KNOWLEDGE_BASE_ID", "default"),
    )
    lifecycle = WikiDocumentLifecycle(store, projection)
    api_key = deepseek_api_key_from_environment()
    client = CachingJsonCompletionClient(
        DeepSeekJsonLLM(api_key=api_key), store,
    )
    confirmation = CachingJsonCompletionClient(
        DeepSeekJsonLLM(api_key=api_key, model="deepseek-v4-flash"), store,
    )
    publishing = _enabled("WIKI_PUBLISH_ENABLED")
    service = WikiBuildService(
        repository=store, extractor=CandidateExtractor(client),
        promotion_selector=CandidatePromotionSelector(
            client, confirmation_client=confirmation,
        ),
        identity_resolver=IdentityResolver(client), taxonomy_planner=TaxonomyPlanner(client),
        page_compiler=WikiPageCompiler(client),
        quality_gate=WikiQualityGate(
            client, client, max_repair_rounds=2,
            confirmation_client=confirmation, page_client=confirmation,
        ),
        config=WikiBuildConfig(enabled=True, publish=publishing),
    )
    vector = BgeM3WikiVectorSearch(store) if _enabled("WIKI_VECTOR_SEARCH_ENABLED") else None
    worker = WikiStageWorker(
        service, lifecycle.load_for_lease, worker_id=args.worker_id,
        vector_indexer=vector,
        scope_filter=WikiScope(
            source_scope="enterprise",
            knowledge_base_id=projection.knowledge_base_id,
        ),
    )
    while True:
        try:
            lifecycle.reconcile()
            lifecycle.coordinator.schedule(
                debounce_seconds=args.debounce_seconds, publish=publishing,
            )
            while worker.run_once():
                pass
        except Exception as exc:
            if args.once:
                raise
            print(f"Wiki worker cycle failed: {type(exc).__name__}", file=sys.stderr, flush=True)
        if args.once:
            return
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
