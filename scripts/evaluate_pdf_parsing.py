"""Evaluate the real PDF parser over local files without embeddings or Milvus."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
for directory in (PROJECT_ROOT, PROJECT_ROOT / "data-pipeline"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from models.document import BlockType, Document  # noqa: E402
from parsers.registry import parse_file  # noqa: E402
from pipeline.structured_ingestion import prepare_ingestion_chunks  # noqa: E402


def discover_pdfs(inputs: list[str]) -> list[Path]:
    """Return unique PDF files from explicit files and recursive directories."""
    discovered: dict[str, Path] = {}
    for raw_path in inputs:
        path = Path(raw_path).expanduser().resolve()
        candidates = path.rglob("*") if path.is_dir() else [path]
        for candidate in candidates:
            if candidate.is_file() and candidate.suffix.casefold() == ".pdf":
                resolved = candidate.resolve()
                discovered[resolved.as_posix().casefold()] = resolved
    return [discovered[key] for key in sorted(discovered)]


def _expectation_result(document: Document, expected: dict | None) -> dict | None:
    if expected is None:
        return None
    failures: list[str] = []
    for text in expected.get("required_text", []):
        if str(text) not in document.content:
            failures.append(f"required_text missing: {text}")
    for text in expected.get("forbidden_text", []):
        if str(text) in document.content:
            failures.append(f"forbidden_text present: {text}")

    accepted_tables = sum(
        block.block_type == BlockType.TABLE
        and block.table is not None
        and block.table.acceptance == "accepted"
        for block in document.content_blocks
    )
    minimum_blocks = int(expected.get("min_content_blocks", 0))
    if len(document.content_blocks) < minimum_blocks:
        failures.append(
            f"content_blocks {len(document.content_blocks)} below minimum {minimum_blocks}"
        )
    minimum_tables = int(expected.get("min_accepted_tables", 0))
    if accepted_tables < minimum_tables:
        failures.append(f"accepted_tables {accepted_tables} below minimum {minimum_tables}")
    return {"passed": not failures, "failures": failures}


def _evaluate_one(
    path: Path,
    *,
    expected: dict | None,
    parser: Callable[[str], Document],
) -> dict:
    started = time.perf_counter()
    try:
        document = parser(str(path))
        chunks = prepare_ingestion_chunks(document)
    except Exception as error:
        return {
            "name": path.name,
            "path": str(path),
            "status": "error",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "error": f"{type(error).__name__}: {error}",
        }

    tables = [
        block.table
        for block in document.content_blocks
        if block.block_type == BlockType.TABLE and block.table is not None
    ]
    sources = Counter(block.source for block in document.content_blocks)
    page_region_count = sum(len(chunk.page_regions) for chunk in chunks)
    located_chunks = sum(bool(chunk.page_regions) for chunk in chunks)
    diagnostics = document.parse_diagnostics
    return {
        "name": path.name,
        "path": str(path),
        "status": "ok",
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "page_count": diagnostics.page_count if diagnostics is not None else 0,
        "content_characters": len(document.content),
        "content_blocks": len(document.content_blocks),
        "chunks": len(chunks),
        "source_blocks": dict(sorted(sources.items())),
        "accepted_tables": sum(table.acceptance == "accepted" for table in tables),
        "review_tables": sum(table.acceptance == "review" for table in tables),
        "page_region_count": page_region_count,
        "located_chunk_ratio": round(located_chunks / len(chunks), 4) if chunks else 0.0,
        "parse_diagnostics": (
            diagnostics.model_dump(mode="json") if diagnostics is not None else None
        ),
        "expectations": _expectation_result(document, expected),
    }


def evaluate_paths(
    inputs: list[str],
    *,
    expectations: dict[str, dict] | None = None,
    parser: Callable[[str], Document] = parse_file,
    max_files: int | None = None,
) -> dict:
    paths = discover_pdfs(inputs)
    if max_files is not None:
        paths = paths[:max(0, max_files)]
    expectations = expectations or {}
    files = [
        _evaluate_one(
            path,
            expected=expectations.get(path.name) or expectations.get(path.as_posix()),
            parser=parser,
        )
        for path in paths
    ]
    parsed = [item for item in files if item["status"] == "ok"]
    summary = {
        "files": len(files),
        "parsed": len(parsed),
        "failed": len(files) - len(parsed),
        "expectation_failures": sum(
            item.get("expectations") is not None
            and not item["expectations"]["passed"]
            for item in parsed
        ),
        "content_characters": sum(item["content_characters"] for item in parsed),
        "content_blocks": sum(item["content_blocks"] for item in parsed),
        "chunks": sum(item["chunks"] for item in parsed),
        "accepted_tables": sum(item["accepted_tables"] for item in parsed),
        "review_tables": sum(item["review_tables"] for item in parsed),
        "ocr_applied_pages": sum(
            len((item.get("parse_diagnostics") or {}).get("ocr_applied_pages", []))
            for item in parsed
        ),
    }
    return {"summary": summary, "files": files}


def main(argv: list[str] | None = None) -> int:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("paths", nargs="+", help="PDF files or directories")
    argument_parser.add_argument("--expectations", help="Optional expectations JSON")
    argument_parser.add_argument("--output", help="Optional report JSON path")
    argument_parser.add_argument("--max-files", type=int)
    args = argument_parser.parse_args(argv)

    expectations = None
    if args.expectations:
        expectations = json.loads(Path(args.expectations).read_text(encoding="utf-8"))
    report = evaluate_paths(
        args.paths,
        expectations=expectations,
        max_files=args.max_files,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    summary = report["summary"]
    return 1 if summary["failed"] or summary["expectation_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
