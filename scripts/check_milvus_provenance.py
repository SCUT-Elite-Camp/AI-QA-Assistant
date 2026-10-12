"""Read-only health check for Milvus PDF provenance fields."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
for directory in (
    PROJECT_ROOT,
    PROJECT_ROOT / "data-persistence",
    PROJECT_ROOT / "toolset",
):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from storage.milvus_store import MilvusStore  # noqa: E402
from tool_layer.search_tool import _page_regions_from_provenance  # noqa: E402


def check_milvus_provenance(
    *,
    host: str | None = None,
    port: str | None = None,
    collection_name: str | None = None,
    sample_limit: int = 100,
    store=None,
) -> dict:
    """Inspect an existing collection without creating or mutating it."""
    collection_name = collection_name or os.getenv("MILVUS_COLLECTION", "doc_chunks")
    resolved_store = store or MilvusStore(host=host, port=port)
    try:
        resolved_store.connect()
        collection = resolved_store.get_existing_collection(collection_name)
        if collection is None:
            return {
                "status": "error",
                "collection": collection_name,
                "error": "collection not found",
            }
        resolved_store.validate_chunk_schema(collection_name)
        rows = collection.query(
            expr="id >= 0",
            output_fields=["chunk_id", "page_number", "bbox_json", "metadata_json"],
            limit=max(1, int(sample_limit)),
        )
    except Exception as error:
        return {
            "status": "error",
            "collection": collection_name,
            "error": f"{type(error).__name__}: {error}",
        }

    structured = 0
    legacy = 0
    missing = 0
    malformed = 0
    for row in rows:
        metadata = {}
        metadata_json = row.get("metadata_json")
        if isinstance(metadata_json, str) and metadata_json:
            try:
                parsed = json.loads(metadata_json)
                metadata = parsed if isinstance(parsed, dict) else {}
            except (json.JSONDecodeError, TypeError):
                malformed += 1
        regions = _page_regions_from_provenance(
            row.get("page_number"),
            row.get("bbox_json"),
            metadata_json,
        )
        raw_regions = metadata.get("page_regions")
        if regions and isinstance(raw_regions, list) and raw_regions:
            structured += 1
        elif regions:
            legacy += 1
        else:
            missing += 1

    return {
        "status": "ok",
        "collection": collection_name,
        "entities": int(getattr(collection, "num_entities", 0) or 0),
        "sampled": len(rows),
        "structured_region_rows": structured,
        "legacy_fallback_rows": legacy,
        "missing_region_rows": missing,
        "malformed_metadata_rows": malformed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.getenv("MILVUS_HOST", "localhost"))
    parser.add_argument("--port", default=os.getenv("MILVUS_PORT", "19530"))
    parser.add_argument("--collection", default=os.getenv("MILVUS_COLLECTION", "doc_chunks"))
    parser.add_argument("--sample-limit", type=int, default=100)
    args = parser.parse_args(argv)

    report = check_milvus_provenance(
        host=args.host,
        port=args.port,
        collection_name=args.collection,
        sample_limit=args.sample_limit,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
