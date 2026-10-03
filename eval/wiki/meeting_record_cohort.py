"""Freeze a private, folder-scoped Confluence meeting-record pilot cohort."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "data-pipeline"))
from pipeline.confluence_snapshot import ConfluenceSnapshot, discover_confluence_snapshots  # noqa: E402


def freeze_meeting_record_cohort(
    snapshots: list[ConfluenceSnapshot], *, space_id: str, parent_page_id: str,
    expected_pages: int | None = None,
) -> dict:
    """Select only descendants of a known Confluence folder/page ID in one space."""
    if not space_id or not parent_page_id:
        raise ValueError("space_id and parent_page_id are required")
    candidates = [item for item in snapshots if item.space_id == space_id]
    by_page_id: dict[str, ConfluenceSnapshot] = {}
    parents: dict[str, str] = {}
    for item in candidates:
        if item.page_id in by_page_id:
            raise ValueError(f"multiple versions of Confluence page {item.page_id}")
        metadata = json.loads(item.metadata_path.read_text(encoding="utf-8-sig"))
        if str(metadata.get("page_id") or "") != item.page_id:
            raise ValueError(f"Confluence page metadata identity mismatch: {item.metadata_path}")
        by_page_id[item.page_id] = item
        parents[item.page_id] = str(metadata.get("parent_id") or "")

    def under_parent(page_id: str) -> bool:
        seen: set[str] = set()
        current = page_id
        while current in parents:
            if current in seen:
                raise ValueError(f"Confluence parent cycle at page {current}")
            seen.add(current)
            parent = parents[current]
            if parent == parent_page_id:
                return True
            current = parent
        return False

    selected = sorted(
        (item for item in candidates if item.page_id != parent_page_id and under_parent(item.page_id)),
        key=lambda item: item.identity,
    )
    if not selected:
        raise ValueError(f"no Confluence pages under parent {parent_page_id}")
    if expected_pages is not None and len(selected) != expected_pages:
        raise ValueError(f"expected {expected_pages} meeting pages, found {len(selected)}")
    if len(selected) > 24:
        raise ValueError("meeting pilot exceeds the 24-page audit limit")
    return {
        "schema_version": 1,
        "selection_rule": "confluence-parent-closure-v1",
        "scope": "MEETING_RECORD_ONLY_EXPLORATORY_PILOT",
        "space_id": space_id,
        "parent_page_id": parent_page_id,
        "pages": [
            {
                "identity": list(item.identity),
                "source_content_sha256": item.source_content_sha256,
                "content_sha256": item.content_sha256,
                "split": "development",
                "category": "meeting_record",
            }
            for item in selected
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze Confluence Meeting Record extraction scope")
    parser.add_argument("confluence_root", type=Path)
    parser.add_argument("--space-id", required=True)
    parser.add_argument("--parent-page-id", required=True)
    parser.add_argument("--expected-pages", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to replace frozen cohort: {args.output}")
    cohort = freeze_meeting_record_cohort(
        discover_confluence_snapshots(args.confluence_root, require_storage=True),
        space_id=args.space_id,
        parent_page_id=args.parent_page_id,
        expected_pages=args.expected_pages,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cohort, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "FROZEN", "pages": len(cohort["pages"]),
                      "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
