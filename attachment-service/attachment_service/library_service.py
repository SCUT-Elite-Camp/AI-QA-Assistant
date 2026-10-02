from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .store import AttachmentStore


def validate_library_configuration(*, library_enabled: bool, vector_enabled: bool) -> None:
    if library_enabled and not vector_enabled:
        raise RuntimeError(
            "PERSONAL_LIBRARY_ENABLED=true requires "
            "ATTACHMENT_VECTOR_INDEX_ENABLED=true"
        )


def resolve_section_search_context(
    query: str,
    versions: list[dict[str, Any]],
) -> tuple[list[str], str]:
    """Turn an explicit document title in the question into a scoped filter.

    Document titles identify where to search; repeating the same title in every
    Section must not become a relevance signal that drowns the actual question.
    The returned attachment ids are always a subset of the already-authorized
    active versions supplied by the caller.
    """
    all_ids = [str(item["id"]) for item in versions]
    matches: list[tuple[str, str]] = []
    query_folded = query.casefold()
    for item in versions:
        title = Path(str(item.get("filename") or "")).stem.strip()
        if len(title) >= 4 and title.casefold() in query_folded:
            matches.append((str(item["id"]), title))
    if not matches:
        return all_ids, query

    cleaned = query
    for _, title in sorted(matches, key=lambda value: len(value[1]), reverse=True):
        cleaned = re.sub(re.escape(title), " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[\s\"'`,:;()\[\]{}]+", " ", cleaned).strip()
    return list(dict.fromkeys(identifier for identifier, _ in matches)), cleaned or query


def rebuild_library_projection(
    store: AttachmentStore,
    vector_index: Any,
    attachment: dict[str, Any],
    evidence: list[dict[str, Any]],
    generation_id: str,
    sections: list[dict[str, Any]] | None = None,
    section_vector_index: Any | None = None,
) -> tuple[str, str]:
    """Build a new vector generation before switching lexical/vector state."""
    new_vector_ref = f"{attachment['id']}__{generation_id}"
    vector_index.replace(new_vector_ref, evidence)
    try:
        if section_vector_index is not None and section_vector_index.enabled:
            section_vector_index.replace(new_vector_ref, sections or [])
    except Exception:
        vector_index.delete(new_vector_ref)
        raise
    previous_vector_ref = str(attachment.get("vector_ref") or "")
    store.replace_evidence(attachment["id"], evidence)
    store.replace_sections(attachment["id"], sections or [])
    store.update_attachment(attachment["id"], vector_ref=new_vector_ref)
    return previous_vector_ref, new_vector_ref


def fuse_section_candidates(
    sections: dict[str, dict[str, Any]],
    sparse: list[dict[str, Any]],
    vector: list[dict[str, Any]],
    *,
    top_k: int,
    rrf_k: int = 60,
) -> list[dict[str, Any]]:
    """RRF Section sparse/vector ranks without treating tree relatives as hits."""
    scores: dict[str, float] = {}
    for rows in (sparse, vector):
        for rank, row in enumerate(rows, 1):
            section_id = str(row.get("id") or row.get("section_id") or "")
            if section_id in sections:
                scores[section_id] = scores.get(section_id, 0.0) + 1.0 / (rrf_k + rank)
    ordered = sorted(scores, key=lambda value: (-scores[value], value))[:top_k]
    maximum = max((scores[value] for value in ordered), default=1.0)
    result: list[dict[str, Any]] = []
    for section_id in ordered:
        item = dict(sections[section_id])
        item["score"] = round(scores[section_id] / maximum, 6) if maximum else 0.0
        result.append(item)
    return result


def fuse_library_candidates(
    evidence: dict[str, dict[str, Any]],
    lexical: list[dict[str, Any]],
    vector: list[dict[str, Any]],
    *,
    mode: str,
    top_k: int,
) -> list[dict[str, Any]]:
    """Rank-calibrate lexical/vector candidates to a stable 0..1 score."""
    ranks: dict[str, list[float]] = {}

    def add(rows: list[dict[str, Any]]) -> None:
        for rank, row in enumerate(rows, 1):
            evidence_id = str(row.get("evidence_id") or "")
            if evidence_id in evidence:
                ranks.setdefault(evidence_id, []).append(1.0 / (1.0 + 0.12 * (rank - 1)))

    if mode in {"bm25", "hybrid"}:
        add(lexical)
    if mode in {"vector", "hybrid"}:
        add(vector)
    items: list[dict[str, Any]] = []
    for evidence_id, source_scores in ranks.items():
        score = sum(source_scores) / len(source_scores)
        if len(source_scores) > 1:
            score = min(1.0, score + 0.05)
        item = dict(evidence[evidence_id])
        item["score"] = round(min(1.0, max(0.0, score)), 6)
        items.append(item)
    return sorted(items, key=lambda item: (-float(item["score"]), str(item["evidence_id"])))[:top_k]


def rank_section_evidence(
    evidence: dict[str, dict[str, Any]],
    evidence_ids: list[str],
    lexical: list[dict[str, Any]],
    vector: list[dict[str, Any]],
    *,
    mode: str,
    top_k: int,
    rrf_k: int = 60,
) -> list[dict[str, Any]]:
    """Fuse real Evidence backend ranks after applying an exact Section scope."""
    allowed = {value for value in evidence_ids if value in evidence}
    scoped_evidence = {key: value for key, value in evidence.items() if key in allowed}
    return fuse_library_candidates(
        scoped_evidence,
        [row for row in lexical if str(row.get("evidence_id") or "") in allowed],
        [row for row in vector if str(row.get("evidence_id") or "") in allowed],
        mode=mode,
        top_k=top_k,
    )
