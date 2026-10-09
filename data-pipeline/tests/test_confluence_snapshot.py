from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pipeline.confluence_snapshot import (
    ConfluenceSnapshotConflict,
    discover_confluence_snapshots,
)


def _copy(
    root: Path, name: str, *, content: str, with_tree: bool, storage: str | None = None,
) -> Path:
    page = root / name
    page.mkdir(parents=True)
    markdown = page / "index.md"
    markdown.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(markdown.read_bytes()).hexdigest()
    metadata = {
        "space_id": "space-1", "page_id": "page-1", "version": 3,
        "content_sha256": digest,
    }
    if storage is not None:
        storage_path = page / "page.storage.xhtml"
        storage_path.write_text(storage, encoding="utf-8")
        metadata["source_content_sha256"] = hashlib.sha256(storage_path.read_bytes()).hexdigest()
        metadata["normalized_content_sha256"] = digest
    (page / "page.meta.json").write_text(json.dumps(metadata), encoding="utf-8")
    if with_tree:
        tree = {**metadata, "nodes": [{"id": "section-1"}]}
        (page / "section-tree.json").write_text(json.dumps(tree), encoding="utf-8")
    return markdown


def test_duplicate_identity_prefers_copy_with_valid_section_tree(tmp_path: Path) -> None:
    _copy(tmp_path, "old", content="# Same\n", with_tree=False)
    canonical = _copy(tmp_path, "new", content="# Same\n", with_tree=True)

    snapshots = discover_confluence_snapshots(tmp_path)

    assert len(snapshots) == 1
    assert snapshots[0].markdown_path == canonical
    assert snapshots[0].identity == ("space-1", "page-1", 3)


def test_duplicate_identity_with_different_hash_is_a_hard_conflict(tmp_path: Path) -> None:
    _copy(tmp_path, "first", content="# First\n", with_tree=True)
    _copy(tmp_path, "second", content="# Second\n", with_tree=True)

    with pytest.raises(ConfluenceSnapshotConflict, match="conflicting content_sha256"):
        discover_confluence_snapshots(tmp_path)


def test_declared_content_hash_must_match_markdown(tmp_path: Path) -> None:
    markdown = _copy(tmp_path, "page", content="# Original\n", with_tree=True)
    markdown.write_text("# Changed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="content hash mismatch"):
        discover_confluence_snapshots(tmp_path)


def test_strict_snapshot_requires_and_validates_authoritative_storage(tmp_path: Path) -> None:
    markdown = _copy(
        tmp_path, "page", content="# Rendered\n", with_tree=True,
        storage="<h1>Rendered</h1>",
    )

    snapshot = discover_confluence_snapshots(tmp_path, require_storage=True)[0]
    assert snapshot.storage_path == markdown.with_name("page.storage.xhtml")
    assert snapshot.source_content_sha256 == hashlib.sha256(
        b"<h1>Rendered</h1>"
    ).hexdigest()

    snapshot.storage_path.write_text("<p>Tampered</p>", encoding="utf-8")
    with pytest.raises(ValueError, match="source content hash mismatch"):
        discover_confluence_snapshots(tmp_path, require_storage=True)


def test_strict_snapshot_rejects_legacy_export_without_storage(tmp_path: Path) -> None:
    _copy(tmp_path, "page", content="# Legacy\n", with_tree=True)

    with pytest.raises(ValueError, match="missing authoritative"):
        discover_confluence_snapshots(tmp_path, require_storage=True)
