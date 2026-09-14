from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfluenceSnapshotConflict(RuntimeError):
    """Raised when one logical Confluence page version has conflicting content."""


@dataclass(frozen=True)
class ConfluenceSnapshot:
    markdown_path: Path
    storage_path: Path | None
    metadata_path: Path
    section_tree_path: Path | None
    space_id: str
    page_id: str
    version: int
    content_sha256: str
    source_content_sha256: str = ""
    normalized_content_sha256: str = ""

    @property
    def identity(self) -> tuple[str, str, int]:
        return self.space_id, self.page_id, self.version


def discover_confluence_snapshots(
    root: str | Path, *, require_storage: bool = False,
) -> list[ConfluenceSnapshot]:
    """Scan metadata, validate content hashes, and select one copy per page version."""
    candidates: list[ConfluenceSnapshot] = []
    for metadata_path in sorted(Path(root).rglob("page.meta.json")):
        metadata = _read_object(metadata_path)
        markdown_path = metadata_path.with_name("index.md")
        if not markdown_path.is_file():
            raise ValueError(f"missing Confluence Markdown: {markdown_path}")
        space_id = str(metadata.get("space_id") or "").strip()
        page_id = str(metadata.get("page_id") or "").strip()
        try:
            version = int(metadata.get("version"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid Confluence version: {metadata_path}") from exc
        storage_path = metadata_path.with_name("page.storage.xhtml")
        declared_hash = str(
            metadata.get("normalized_content_sha256") or metadata.get("content_sha256") or ""
        ).strip().lower()
        actual_hash = hashlib.sha256(markdown_path.read_bytes()).hexdigest()
        if not space_id or not page_id or version < 0 or len(declared_hash) != 64:
            raise ValueError(f"invalid Confluence identity metadata: {metadata_path}")
        if declared_hash != actual_hash:
            raise ValueError(f"Confluence content hash mismatch: {markdown_path}")
        source_hash = str(metadata.get("source_content_sha256") or "").strip().lower()
        if storage_path.is_file():
            actual_source_hash = hashlib.sha256(storage_path.read_bytes()).hexdigest()
            if len(source_hash) != 64 or source_hash != actual_source_hash:
                raise ValueError(f"Confluence source content hash mismatch: {storage_path}")
        else:
            actual_source_hash = ""
        tree_path = metadata_path.with_name("section-tree.json")
        candidates.append(ConfluenceSnapshot(
            markdown_path=markdown_path,
            storage_path=storage_path if storage_path.is_file() else None,
            metadata_path=metadata_path,
            section_tree_path=tree_path if tree_path.is_file() else None,
            space_id=space_id,
            page_id=page_id,
            version=version,
            content_sha256=actual_hash,
            source_content_sha256=actual_source_hash,
            normalized_content_sha256=actual_hash,
        ))

    selected: dict[tuple[str, str, int], ConfluenceSnapshot] = {}
    for candidate in candidates:
        current = selected.get(candidate.identity)
        if current is None:
            selected[candidate.identity] = candidate
            continue
        if current.content_sha256 != candidate.content_sha256:
            identity = "/".join((candidate.space_id, candidate.page_id, str(candidate.version)))
            raise ConfluenceSnapshotConflict(
                f"conflicting content_sha256 for Confluence page version {identity}"
            )
        if (
            current.source_content_sha256
            and candidate.source_content_sha256
            and current.source_content_sha256 != candidate.source_content_sha256
        ):
            identity = "/".join((candidate.space_id, candidate.page_id, str(candidate.version)))
            raise ConfluenceSnapshotConflict(
                f"conflicting source_content_sha256 for Confluence page version {identity}"
            )
        # A valid exported tree is preferred over a stale path-only duplicate.
        chosen = min(
            (current, candidate),
            key=lambda item: (
                0 if item.storage_path is not None else 1,
                0 if _has_valid_tree(item) else 1,
                item.markdown_path.as_posix().casefold(),
            ),
        )
        selected[candidate.identity] = chosen
    result = [selected[key] for key in sorted(selected)]
    if require_storage:
        missing = [item.metadata_path.with_name("page.storage.xhtml") for item in result if item.storage_path is None]
        if missing:
            raise ValueError(f"missing authoritative Confluence storage XHTML: {missing[0]}")
    return result


def deduplicate_confluence_paths(paths: list[str]) -> list[str]:
    """Replace exported index.md copies with identity-deduplicated canonical paths."""
    ordinary: list[str] = []
    roots: set[Path] = set()
    for raw in paths:
        path = Path(raw)
        if path.name.casefold() == "index.md" and path.with_name("page.meta.json").is_file():
            roots.add(_export_root(path))
        else:
            ordinary.append(str(path))
    confluence = [
        str(snapshot.markdown_path)
        for root in sorted(roots, key=lambda value: value.as_posix().casefold())
        for snapshot in discover_confluence_snapshots(root)
    ]
    return sorted(dict.fromkeys([*ordinary, *confluence]), key=str.casefold)


def _export_root(path: Path) -> Path:
    current = path.parent
    while current.parent != current and not (current / "manifest.json").is_file():
        if current.name.casefold() == "confluence":
            return current
        current = current.parent
    return current


def _has_valid_tree(snapshot: ConfluenceSnapshot) -> bool:
    if snapshot.section_tree_path is None:
        return False
    try:
        tree = _read_object(snapshot.section_tree_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return (
        str(tree.get("page_id") or "") == snapshot.page_id
        and int(tree.get("version") or -1) == snapshot.version
        and str(tree.get("content_sha256") or "").lower() == snapshot.content_sha256
        and isinstance(tree.get("nodes"), list)
    )


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value
