"""Run the frozen Meeting Record cohort through the generic Wiki pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
for dependency in (ROOT, ROOT / "data-pipeline", ROOT / "data-persistence"):
    if str(dependency) not in sys.path:
        sys.path.insert(0, str(dependency))

from pipeline.confluence_snapshot import discover_confluence_snapshots  # noqa: E402
from pipeline.wiki.llm import DeepSeekJsonLLM, deepseek_api_key_from_environment  # noqa: E402
from pipeline.wiki.confluence_source import load_authoritative_confluence_document  # noqa: E402
from pipeline.wiki.domain import WikiScope  # noqa: E402
from pipeline.wiki.cache import CachingJsonCompletionClient  # noqa: E402
from pipeline.wiki.extraction import CandidateExtractor, CandidatePromotionSelector  # noqa: E402
from pipeline.wiki.identity import IdentityResolver  # noqa: E402
from pipeline.wiki.job import WikiBuildConfig, WikiBuildService  # noqa: E402
from pipeline.wiki.page import WikiPageCompiler  # noqa: E402
from pipeline.wiki.quality import WikiQualityGate  # noqa: E402
from pipeline.wiki.source import document_to_wiki_source  # noqa: E402
from pipeline.wiki.taxonomy import TaxonomyPlanner  # noqa: E402
from storage.wiki_store import WikiStore  # noqa: E402


class _ProgressClient:
    def __init__(self, client: CachingJsonCompletionClient) -> None:
        self.client = client
        self.model = client.model
        self.calls = 0

    def complete(self, **kwargs):
        self.calls += 1
        schema_name = kwargs.get("schema_name", "unknown")
        print(f"wiki-llm call={self.calls} stage={schema_name} start", file=sys.stderr, flush=True)
        value = self.client.complete(**kwargs)
        print(f"wiki-llm call={self.calls} stage={schema_name} done", file=sys.stderr, flush=True)
        return value


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Build the frozen Meeting Record Wiki pilot")
    value.add_argument("confluence_root", type=Path)
    value.add_argument("--cohort", type=Path, required=True)
    value.add_argument("--run-dir", type=Path, required=True)
    value.add_argument("--model", default="deepseek-v4-pro")
    value.add_argument("--strict-audit", action="store_true",
                       help="Require independent promotion/Claim review and page coherence checks")
    value.add_argument("--publish", action="store_true", help="Atomically publish only if every page passes the AI gate")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    key = deepseek_api_key_from_environment()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is required")
    cohort = json.loads(args.cohort.read_text(encoding="utf-8-sig"))
    selected_identities = {tuple(item["identity"]) for item in cohort.get("pages") or []}
    if not selected_identities:
        raise ValueError("frozen cohort contains no pages")
    snapshots = {
        item.identity: item
        for item in discover_confluence_snapshots(args.confluence_root, require_storage=True)
    }
    missing = selected_identities - set(snapshots)
    if missing:
        raise ValueError(f"frozen cohort pages are missing from Confluence export: {sorted(missing)}")
    for item in cohort["pages"]:
        snapshot = snapshots[tuple(item["identity"])]
        if (snapshot.content_sha256 != item["content_sha256"] or
                snapshot.source_content_sha256 != item["source_content_sha256"]):
            raise ValueError(f"frozen cohort content changed: {item['identity']}")
    scope = WikiScope(
        source_scope="enterprise",
        knowledge_base_id=str(cohort.get("space_id") or "").strip(),
    )
    documents = [
        document_to_wiki_source(
            load_authoritative_confluence_document(snapshots[identity]), scope
        )
        for identity in sorted(selected_identities)
    ]
    args.run_dir.mkdir(parents=True, exist_ok=True)
    api_client = DeepSeekJsonLLM(api_key=key, model=args.model)
    store = WikiStore(args.run_dir / "wiki.sqlite3")
    completion_cache = CachingJsonCompletionClient(api_client, store)
    client = _ProgressClient(completion_cache)
    confirmation_api = (
        DeepSeekJsonLLM(api_key=key, model=(
            "deepseek-v4-flash" if args.model == "deepseek-v4-pro" else "deepseek-v4-pro"
        )) if args.strict_audit else None
    )
    confirmation_cache = (
        CachingJsonCompletionClient(confirmation_api, store)
        if confirmation_api is not None else None
    )
    confirmation = _ProgressClient(confirmation_cache) if confirmation_cache else None
    service = WikiBuildService(
        repository=store,
        extractor=CandidateExtractor(client),
        promotion_selector=CandidatePromotionSelector(
            client, confirmation_client=confirmation,
        ),
        identity_resolver=IdentityResolver(client),
        taxonomy_planner=TaxonomyPlanner(client),
        page_compiler=WikiPageCompiler(client),
        quality_gate=WikiQualityGate(
            client, client, max_repair_rounds=2,
            confirmation_client=confirmation, page_client=confirmation,
        ),
        config=WikiBuildConfig(enabled=True, publish=args.publish),
    )
    try:
        result = service.run(documents)
        manifest = {
            "evaluation_label": "PROBE",
            "corpus": "MEETING_RECORD_FROZEN_COHORT",
            "cohort_sha256": _sha256(args.cohort),
            "source_pages": len(documents),
            "result": result.model_dump(mode="json"),
            "model": client.model,
            "strict_audit": args.strict_audit,
            "token_usage": api_client.usage,
            "confirmation_token_usage": confirmation_api.usage if confirmation_api else None,
            "completion_cache": {
                "hits": completion_cache.cache_hits, "misses": completion_cache.cache_misses,
            },
            "citation_authority": False,
            "human_review": "NOT_RUN",
            "formal_retrieval_evaluation": "NOT_RUN",
        }
    except Exception as exc:
        manifest = {
            "evaluation_label": "PROBE", "status": "FAILED", "published": False,
            "source_pages": len(documents), "model": client.model, "token_usage": api_client.usage,
            "strict_audit": args.strict_audit,
            "completion_cache": {
                "hits": completion_cache.cache_hits, "misses": completion_cache.cache_misses,
            },
            "failure": {"type": type(exc).__name__, "message": str(exc)},
            "human_review": "NOT_RUN", "formal_retrieval_evaluation": "NOT_RUN",
        }
        (args.run_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        raise
    (args.run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


def _sha256(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
