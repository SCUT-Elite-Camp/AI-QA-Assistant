"""Read-only comparison of one live Confluence space and a local full export."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for dependency in (ROOT, ROOT / "data-pipeline"):
    sys.path.insert(0, str(dependency))

from confluence_export import ConfluenceClient, load_confluence_config  # noqa: E402
from pipeline.rag_lifecycle import pending_confluence_retractions  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--export-dir", type=Path, required=True)
    parser.add_argument("--documents-dir", type=Path, required=True)
    parser.add_argument("--space-key", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    client = ConfluenceClient(
        **load_confluence_config(args.env_file), timeout=15, max_attempts=2,
    )
    space = client.get_space_by_key(args.space_key)
    space_id = str(space["id"])
    pages = client.list_pages(space_id)
    live_ids = {page.page_id for page in pages}
    if len(live_ids) != len(pages):
        raise ValueError("live Confluence page listing contains duplicate IDs")
    manifest = json.loads((args.export_dir / args.space_key / "manifest.json").read_text(
        encoding="utf-8",
    ))
    if (manifest.get("status") != "ok" or manifest.get("full_sync") is not True
            or str(manifest.get("space_id")) != space_id):
        raise ValueError("local export is not a successful full snapshot of the live space")
    exported_ids = set(manifest.get("pages") or {})
    pending = pending_confluence_retractions(args.documents_dir, args.export_dir)
    report = {
        "evaluation_label": "LIVE_READ_ONLY_LIFECYCLE_CHECK",
        "status": "PASS" if live_ids == exported_ids else "PARTIAL",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "space_key": args.space_key,
        "live_pages": len(live_ids),
        "exported_pages": len(exported_ids),
        "live_only_pages": len(live_ids - exported_ids),
        "export_only_pages": len(exported_ids - live_ids),
        "pending_rag_retractions": len(pending),
        "live_delete_event": "NOT_RUN" if not exported_ids - live_ids else "OBSERVED",
        "production_modified": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
