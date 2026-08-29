from dataclasses import dataclass
from typing import Any, Dict, Iterable, List


def chunk_key(row: Dict[str, Any]) -> tuple:
    return str(row.get("doc_id")), int(row.get("chunk_index", 0))


@dataclass(frozen=True)
class RetrievalPath:
    query_id: str
    retriever: str
    query_weight: float
    retriever_weight: float
    rows: List[Dict[str, Any]]

    @property
    def path_id(self) -> str:
        return f"{self.query_id}:{self.retriever}"


def weighted_rrf(
    paths: Iterable[RetrievalPath],
    top_k: int,
    rrf_k: int = 60,
) -> List[Dict[str, Any]]:
    """Fuse ranked paths while retaining internal provenance for observability."""
    merged: Dict[tuple, Dict[str, Any]] = {}
    best_rank: Dict[tuple, int] = {}

    for path in paths:
        for rank, item in enumerate(path.rows, start=1):
            key = chunk_key(item)
            row = merged.setdefault(
                key,
                {
                    **item,
                    "fusion_score": 0.0,
                    "matched_query_ids": [],
                    "matched_retrievers": [],
                    "raw_rank_by_path": {},
                },
            )
            row["fusion_score"] += (
                path.query_weight * path.retriever_weight / (rrf_k + rank)
            )
            if path.retriever == "vector":
                row["vector_score"] = float(item.get("vector_score", 0.0))
            elif path.retriever == "bm25":
                row["bm25_score"] = float(item.get("bm25_score", 0.0))
            if path.query_id not in row["matched_query_ids"]:
                row["matched_query_ids"].append(path.query_id)
            if path.retriever not in row["matched_retrievers"]:
                row["matched_retrievers"].append(path.retriever)
            row["raw_rank_by_path"][path.path_id] = rank
            best_rank[key] = min(best_rank.get(key, rank), rank)

    rows = list(merged.values())
    rows.sort(
        key=lambda row: (
            -row["fusion_score"],
            best_rank[chunk_key(row)],
            chunk_key(row),
        )
    )
    scores = [row["fusion_score"] for row in rows]
    if scores:
        low, high = min(scores), max(scores)
        for row in rows:
            if abs(high - low) < 1e-12:
                row["score"] = 1.0 if high > 0 else 0.0
            else:
                row["score"] = (row["fusion_score"] - low) / (high - low)
    return rows[:top_k]


def weighted_rrf_with_reserves(
    paths: Iterable[RetrievalPath],
    top_k: int,
    original_reserve: int = 5,
    variant_unique_reserve: int = 2,
    rrf_k: int = 60,
) -> tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Fuse paths while reserving original and rewrite-exclusive candidates."""
    paths = list(paths)
    unique_count = len(
        {chunk_key(row) for path in paths for row in path.rows}
    )
    if not unique_count or top_k <= 0:
        return [], {"original": 0, "variant_unique": 0}

    fused = weighted_rrf(paths, unique_count, rrf_k)
    fused_by_key = {chunk_key(row): row for row in fused}
    original_paths = [path for path in paths if path.query_id == "q0"]
    original_universe = {
        chunk_key(row) for path in original_paths for row in path.rows
    }
    reserved_original = weighted_rrf(
        original_paths, min(original_reserve, top_k), rrf_k
    )

    reserved_variant = []
    variant_ids = list(
        dict.fromkeys(path.query_id for path in paths if path.query_id != "q0")
    )
    for query_id in variant_ids:
        variant_paths = [path for path in paths if path.query_id == query_id]
        variant_count = len(
            {chunk_key(row) for path in variant_paths for row in path.rows}
        )
        candidates = weighted_rrf(variant_paths, variant_count, rrf_k)
        exclusive = [
            row for row in candidates if chunk_key(row) not in original_universe
        ]
        reserved_variant.extend(exclusive[:variant_unique_reserve])

    reserved_keys = []
    for row in reserved_original + reserved_variant:
        key = chunk_key(row)
        if key in fused_by_key and key not in reserved_keys:
            reserved_keys.append(key)
    selected = set(reserved_keys[:top_k])
    for row in fused:
        if len(selected) >= top_k:
            break
        selected.add(chunk_key(row))
    final = [row for row in fused if chunk_key(row) in selected]
    original_keys = {chunk_key(row) for row in reserved_original}
    variant_keys = {chunk_key(row) for row in reserved_variant}
    return final[:top_k], {
        "original": len(selected & original_keys),
        "variant_unique": len(selected & variant_keys),
    }
