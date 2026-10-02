"""Create a small, reproducible FinanceBench baseline for the CP2 Agent.

The official corpus remains under eval/datasets/external (gitignored). The
derived JSON manifest is small and reviewable; only PDFs needed by the selected
cases are copied into a local subset directory for later indexing.
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "eval" / "datasets" / "external" / "financebench"
DEFAULT_OUTPUT = ROOT / "eval" / "datasets" / "financebench_agent_cases.json"
DEFAULT_SUBSET = ROOT / "eval" / "datasets" / "external" / "financebench_subset"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def select_diverse_cases(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    """Round-robin reasoning types while preferring new companies/documents."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(rows, key=lambda item: item["financebench_id"]):
        grouped[row.get("question_reasoning") or "unspecified"].append(row)

    selected: list[dict[str, Any]] = []
    used_companies: set[str] = set()
    used_docs: set[str] = set()
    reasoning_types = sorted(grouped)
    while len(selected) < count:
        progressed = False
        for reasoning in reasoning_types:
            candidates = grouped[reasoning]
            candidate = next(
                (row for row in candidates if row["doc_name"] not in used_docs and row["company"] not in used_companies),
                None,
            )
            if candidate is None:
                candidate = next((row for row in candidates if row["doc_name"] not in used_docs), None)
            if candidate is None:
                continue
            candidates.remove(candidate)
            selected.append(candidate)
            used_companies.add(candidate["company"])
            used_docs.add(candidate["doc_name"])
            progressed = True
            if len(selected) == count:
                break
        if not progressed:
            break
    if len(selected) < count:
        raise ValueError(f"could only select {len(selected)} unique-document cases")
    return selected


def convert_case(row: dict[str, Any]) -> dict[str, Any]:
    evidence = row.get("evidence") or []
    return {
        "id": f"financebench_{row['financebench_id']}",
        "query": row["question"],
        "expected_intent": "knowledge_qa",
        "should_clarify": False,
        "reference_answer": row["answer"],
        "answer_justification": row.get("justification", ""),
        "required_facts": [[row["answer"]]],
        "min_fact_groups": 1,
        "min_citations": 1,
        "expected_doc_names": sorted({item["doc_name"] for item in evidence}),
        "expected_evidence": [
            {
                "doc_name": item["doc_name"],
                "page_number_zero_based": item["evidence_page_num"],
                "evidence_text": item["evidence_text"],
            }
            for item in evidence
        ],
        "financebench": {
            "source_id": row["financebench_id"],
            "company": row["company"],
            "doc_name": row["doc_name"],
            "question_type": row.get("question_type"),
            "question_reasoning": row.get("question_reasoning"),
        },
    }


def build(source: Path, output: Path, subset_dir: Path, count: int) -> dict[str, Any]:
    rows = read_jsonl(source / "data" / "financebench_open_source.jsonl")
    selected = select_diverse_cases(rows, count)
    pdf_dir = subset_dir / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    for row in selected:
        source_pdf = source / "pdfs" / f"{row['doc_name']}.pdf"
        if not source_pdf.exists():
            raise FileNotFoundError(source_pdf)
        shutil.copy2(source_pdf, pdf_dir / source_pdf.name)

    payload = {
        "metadata": {
            "name": "FinanceBench CP2 Agent baseline",
            "source": "https://github.com/patronus-ai/financebench",
            "source_open_cases": len(rows),
            "selected_cases": len(selected),
            "selection": "deterministic round-robin by reasoning type with unique documents",
            "local_pdf_directory": "eval/datasets/external/financebench_subset/pdfs",
        },
        "component_cases": [],
        "quality_cases": [convert_case(row) for row in selected],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a FinanceBench Agent subset")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--subset-dir", type=Path, default=DEFAULT_SUBSET)
    parser.add_argument("--count", type=int, default=20)
    args = parser.parse_args()
    payload = build(args.source, args.output, args.subset_dir, args.count)
    print(json.dumps({"output": str(args.output), "selected_cases": len(payload["quality_cases"]), "pdf_dir": payload["metadata"]["local_pdf_directory"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
