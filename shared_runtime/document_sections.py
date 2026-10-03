from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from typing import Any


SECTION_QUALITY = {"high", "low"}
SUMMARY_STATES = {"not_requested", "pending", "active", "failed", "stale"}


def stable_document_version_id(
    *,
    source_scope: str,
    knowledge_base_id: str,
    document_id: str,
    version: str | int,
    content_sha256: str,
) -> str:
    """Return the canonical content-bound identifier for a document version.

    Paths are deliberately excluded: moving an exported Confluence page or a
    personal-library file must not create a different logical version.
    """
    values = (
        _clean(source_scope).casefold(),
        _clean(knowledge_base_id),
        _clean(document_id),
        _clean(version),
        _clean(content_sha256).casefold(),
    )
    if any(not value for value in values):
        raise ValueError("document version identity fields must be non-empty")
    digest = hashlib.sha256(":".join(values).encode("utf-8")).hexdigest()
    return f"ver_{digest}"


def stable_section_id(version_id: str, path: Iterable[str], ordinal: int = 0) -> str:
    """Return a deterministic ID in the Section namespace for one document version."""
    normalized = " / ".join(_clean(value) for value in path if _clean(value))
    digest = hashlib.sha256(
        f"{version_id}:{normalized}:{int(ordinal)}".encode("utf-8")
    ).hexdigest()[:20]
    return f"sec_{digest}"


def build_navigation_text(
    section: Mapping[str, Any],
    *,
    document_title: str = "",
    page_ancestor_path: Iterable[str] = (),
    aliases: Iterable[str] = (),
) -> str:
    """Build the canonical sparse/vector text for a Section navigation node."""
    values: list[str] = []
    values.append(document_title)
    values.extend(page_ancestor_path)
    path = section.get("section_path") or []
    if isinstance(path, str):
        values.append(path)
    else:
        values.extend(str(value) for value in path)
    values.extend([
        str(section.get("title") or ""),
        str(section.get("extractive_summary") or section.get("summary") or ""),
        str(section.get("llm_summary") or ""),
    ])
    values.extend(aliases)
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        clean = _clean(value)
        key = clean.casefold()
        if clean and key not in seen:
            output.append(clean)
            seen.add(key)
    return "\n".join(output)


def normalize_section(
    section: Mapping[str, Any],
    *,
    version_id: str,
    document_title: str,
    page_ancestor_path: Iterable[str] = (),
    aliases: Iterable[str] = (),
) -> dict[str, Any]:
    """Normalize provider output to the shared, persistence-safe Section contract."""
    row = dict(section)
    path_value = row.get("section_path") or [document_title]
    path = [
        _clean(value) for value in (
            [path_value] if isinstance(path_value, str) else path_value
        ) if _clean(value)
    ]
    if not path:
        path = [_clean(document_title) or "Untitled"]
    ordinal = int(row.get("ordinal") or 0)
    extractive = _clean(row.get("extractive_summary") or row.get("summary") or "")
    llm_summary = _clean(row.get("llm_summary") or "")
    quality = str(row.get("quality") or "low").casefold()
    if quality not in SECTION_QUALITY:
        quality = "low"
    summary_status = str(row.get("summary_status") or "not_requested").casefold()
    if summary_status not in SUMMARY_STATES:
        summary_status = "failed"
    row.update({
        "id": str(row.get("id") or stable_section_id(version_id, path, ordinal)),
        "version_id": version_id,
        "parent_id": row.get("parent_id"),
        "level": max(0, min(5, int(row.get("level") or 0))),
        "title": _clean(row.get("title") or path[-1]),
        "section_path": path,
        "page_start": _optional_int(row.get("page_start")),
        "page_end": _optional_int(row.get("page_end")),
        "line_start": _optional_int(row.get("line_start")),
        "line_end": _optional_int(row.get("line_end")),
        "summary": extractive,
        "extractive_summary": extractive,
        "llm_summary": llm_summary,
        "summary_type": str(row.get("summary_type") or ("extractive" if extractive else "")),
        "summary_model": str(row.get("summary_model") or ""),
        "summary_prompt_version": str(row.get("summary_prompt_version") or ""),
        "summary_input_hash": str(row.get("summary_input_hash") or ""),
        "summary_status": summary_status,
        "evidence_ids": _string_list(row.get("evidence_ids")),
        "own_block_ids": _string_list(row.get("own_block_ids")),
        "subtree_block_ids": _string_list(row.get("subtree_block_ids")),
        "quality": quality,
        "provenance": str(row.get("provenance") or "native"),
        "ordinal": ordinal,
    })
    row["navigation_text"] = build_navigation_text(
        row,
        document_title=document_title,
        page_ancestor_path=page_ancestor_path,
        aliases=aliases,
    )
    return row


def select_outline_candidates(
    sections: Iterable[Mapping[str, Any]],
    matched: Iterable[Mapping[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Return bounded tree context around matched Sections.

    Ancestors and immediate children are navigation choices only. They keep
    their relationship label and never inherit a matched node's score.
    """
    maximum = max(1, int(limit))
    rows = [dict(item) for item in sections]
    by_id = {
        str(item.get("id") or ""): item
        for item in rows if str(item.get("id") or "")
    }
    children: dict[str, list[dict[str, Any]]] = {}
    for item in rows:
        parent_id = str(item.get("parent_id") or "")
        if parent_id:
            children.setdefault(parent_id, []).append(item)
    for values in children.values():
        values.sort(key=lambda item: (
            int(item.get("ordinal") or 0), str(item.get("id") or "")
        ))

    output: list[dict[str, Any]] = []
    seen: set[str] = set()

    def append(item: Mapping[str, Any], relation: str, *, keep_score: bool) -> None:
        section_id = str(item.get("id") or "")
        if not section_id or section_id in seen or len(output) >= maximum:
            return
        row = dict(item)
        row["navigation_relation"] = relation
        if not keep_score:
            row.pop("score", None)
        output.append(row)
        seen.add(section_id)

    seeds = [dict(item) for item in matched if str(item.get("id") or "") in by_id]
    for seed in seeds:
        append(seed, "matched", keep_score=True)
    for seed in seeds:
        ancestry: list[dict[str, Any]] = []
        parent_id = str(seed.get("parent_id") or "")
        while parent_id and parent_id in by_id:
            parent = by_id[parent_id]
            ancestry.append(parent)
            parent_id = str(parent.get("parent_id") or "")
        for parent in reversed(ancestry):
            append(parent, "ancestor", keep_score=False)
        for child in children.get(str(seed.get("id") or ""), []):
            append(child, "child", keep_score=False)

    if not output:
        reliable = [item for item in rows if str(item.get("quality") or "high") != "low"]
        top_level = [item for item in reliable if int(item.get("level") or 0) == 1]
        fallback = top_level or [item for item in reliable if not item.get("parent_id")] or reliable
        fallback.sort(key=lambda item: (
            str(item.get("attachment_id") or item.get("doc_id") or ""),
            int(item.get("ordinal") or 0),
            str(item.get("id") or ""),
        ))
        for item in fallback:
            append(item, "top_level", keep_score=False)
    return output[:maximum]


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return list(dict.fromkeys(str(item) for item in value if str(item).strip()))


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
