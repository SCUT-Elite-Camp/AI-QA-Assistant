from __future__ import annotations

from typing import Any

from .store import AttachmentStore


def validate_library_configuration(*, library_enabled: bool, vector_enabled: bool) -> None:
    if library_enabled and not vector_enabled:
        raise RuntimeError(
            "PERSONAL_LIBRARY_ENABLED=true requires "
            "ATTACHMENT_VECTOR_INDEX_ENABLED=true"
        )


def rebuild_library_projection(
    store: AttachmentStore,
    vector_index: Any,
    attachment: dict[str, Any],
    evidence: list[dict[str, Any]],
    generation_id: str,
    sections: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """Build a new vector generation before switching lexical/vector state."""
    new_vector_ref = f"{attachment['id']}__{generation_id}"
    vector_index.replace(new_vector_ref, evidence)
    previous_vector_ref = str(attachment.get("vector_ref") or "")
    store.replace_evidence(attachment["id"], evidence)
    store.replace_sections(attachment["id"], sections or [])
    store.update_attachment(attachment["id"], vector_ref=new_vector_ref)
    return previous_vector_ref, new_vector_ref


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


def fuse_navigation_candidates(
    direct: list[dict[str, Any]],
    scoped: list[dict[str, Any]],
    *,
    top_k: int,
    direct_weight: float = 1.0,
    scoped_weight: float = 1.2,
    rrf_k: int = 60,
) -> list[dict[str, Any]]:
    """Fuse direct and section-guided Evidence without making navigation authoritative."""
    by_id: dict[str, dict[str, Any]] = {}
    scores: dict[str, float] = {}
    for weight, rows in ((direct_weight, direct), (scoped_weight, scoped)):
        for rank, item in enumerate(rows, 1):
            evidence_id = str(item.get("evidence_id") or "")
            if not evidence_id:
                continue
            by_id.setdefault(evidence_id, dict(item))
            scores[evidence_id] = scores.get(evidence_id, 0.0) + weight / (rrf_k + rank)
    ordered = sorted(scores, key=lambda value: (-scores[value], value))[:top_k]
    if not ordered:
        return []
    maximum = max(scores[value] for value in ordered) or 1.0
    result = []
    for evidence_id in ordered:
        item = dict(by_id[evidence_id])
        item["score"] = round(min(1.0, scores[evidence_id] / maximum), 6)
        result.append(item)
    return result


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
    """Materialize all selected-section Evidence, then add backend rank signals."""
    allowed = {value for value in evidence_ids if value in evidence}
    scores: dict[str, float] = {}
    for rank, evidence_id in enumerate(evidence_ids, 1):
        if evidence_id in allowed:
            scores[evidence_id] = scores.get(evidence_id, 0.0) + 1.0 / (rrf_k + rank)
    sources: list[list[dict[str, Any]]] = []
    if mode in {"bm25", "hybrid"}:
        sources.append(lexical)
    if mode in {"vector", "hybrid"}:
        sources.append(vector)
    for rows in sources:
        for rank, row in enumerate(rows, 1):
            evidence_id = str(row.get("evidence_id") or "")
            if evidence_id in allowed:
                scores[evidence_id] = scores.get(evidence_id, 0.0) + 0.5 / (rrf_k + rank)
    ordered = sorted(scores, key=lambda value: (-scores[value], value))[:top_k]
    maximum = max((scores[value] for value in ordered), default=1.0)
    result: list[dict[str, Any]] = []
    for evidence_id in ordered:
        item = dict(evidence[evidence_id])
        item["score"] = round(scores[evidence_id] / maximum, 6) if maximum else 0.0
        result.append(item)
    return result
