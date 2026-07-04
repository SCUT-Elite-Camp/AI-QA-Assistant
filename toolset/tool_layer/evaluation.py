import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Union


DEFAULT_K_VALUES = (1, 3, 5)


def evaluate_retrieval(
    search_tool,
    eval_cases: Union[str, Path, Iterable[Dict]],
    mode: str = "hybrid",
    output_path: Optional[Union[str, Path]] = "eval_results.json",
    k_values: Sequence[int] = DEFAULT_K_VALUES,
) -> Dict:
    """Evaluate a search tool with Hit Rate@K and MRR."""
    cases = _load_eval_cases(eval_cases)
    k_values = tuple(sorted({int(k) for k in k_values if int(k) > 0}))
    if not k_values:
        raise ValueError("k_values must contain at least one positive integer")

    max_k = max(k_values)
    per_case = []
    hit_counts = {k: 0 for k in k_values}
    reciprocal_rank_total = 0.0

    for index, case in enumerate(cases):
        query = case.get("query")
        relevant = _relevant_keys(case)
        if not query or not relevant:
            raise ValueError(f"eval case {index} must include query and relevant documents")

        results = search_tool.search(
            query=query,
            top_k=max_k,
            mode=case.get("mode", mode),
            filters=case.get("filters"),
            min_score=case.get("min_score", 0.0),
            trace_id=case.get("trace_id", f"eval-{index}"),
        )
        result_keys = [_result_keys(row) for row in results]
        first_rank = _first_relevant_rank(result_keys, relevant)

        for k in k_values:
            if first_rank is not None and first_rank <= k:
                hit_counts[k] += 1

        reciprocal_rank = 0.0 if first_rank is None else 1.0 / first_rank
        reciprocal_rank_total += reciprocal_rank
        per_case.append(
            {
                "query": query,
                "expected": sorted(relevant),
                "top_results": [
                    {
                        "doc_id": row.get("doc_id"),
                        "chunk_index": row.get("chunk_index"),
                        "score": row.get("score"),
                    }
                    for row in results
                ],
                "first_relevant_rank": first_rank,
                "reciprocal_rank": reciprocal_rank,
            }
        )

    total = len(cases)
    metrics = {f"hit_rate@{k}": _rate(hit_counts[k], total) for k in k_values}
    metrics["mrr"] = _rate(reciprocal_rank_total, total)

    report = {
        "mode": mode,
        "case_count": total,
        "metrics": metrics,
        "cases": per_case,
    }

    if output_path is not None:
        _write_json(output_path, report)

    return report


def _load_eval_cases(eval_cases: Union[str, Path, Iterable[Dict]]) -> List[Dict]:
    if isinstance(eval_cases, (str, Path)):
        path = Path(eval_cases)
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = list(eval_cases)

    if isinstance(data, dict):
        data = data.get("cases", [])

    if not isinstance(data, list):
        raise ValueError("eval_cases must be a list or an object with a cases list")

    return data


def _relevant_keys(case: Dict) -> set:
    keys = set()

    for field in ("relevant_doc_ids", "expected_doc_ids"):
        for doc_id in case.get(field, []) or []:
            keys.add(str(doc_id))

    for field in ("relevant_chunks", "expected_chunks"):
        for chunk in case.get(field, []) or []:
            if isinstance(chunk, dict):
                doc_id = chunk.get("doc_id")
                chunk_index = chunk.get("chunk_index")
                if doc_id is not None and chunk_index is not None:
                    keys.add(f"{doc_id}::{int(chunk_index)}")
            else:
                keys.add(str(chunk))

    return keys


def _result_keys(row: Dict) -> set:
    doc_id = str(row.get("doc_id"))
    chunk_index = row.get("chunk_index")
    keys = {doc_id}
    if chunk_index is not None:
        keys.add(f"{doc_id}::{int(chunk_index)}")
    return keys


def _first_relevant_rank(result_keys: List[set], relevant: set) -> Optional[int]:
    for index, keys in enumerate(result_keys, start=1):
        if keys & relevant:
            return index
    return None


def _rate(value: float, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(value / total, 6)


def _write_json(output_path: Union[str, Path], report: Dict) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
