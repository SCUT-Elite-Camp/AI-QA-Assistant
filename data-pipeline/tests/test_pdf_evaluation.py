import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT, ROOT / "data-pipeline"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from models.document import (  # noqa: E402
    BlockType,
    BoundingBox,
    ContentBlock,
    Document,
    ParseDiagnostics,
    TableArtifact,
    TableCell,
)
from scripts.evaluate_pdf_parsing import discover_pdfs, evaluate_paths  # noqa: E402


def parsed_document(path: str) -> Document:
    if Path(path).name == "broken.pdf":
        raise RuntimeError("cannot parse")
    table = TableArtifact(
        table_id="t1",
        cells=[TableCell(row_index=0, column_index=0, text="Header", is_header=True)],
        row_count=1,
        column_count=1,
        header_row_count=1,
        page_number=1,
        bbox=BoundingBox(x0=10, y0=20, x1=100, y1=80),
        parser_name="test",
        confidence=0.9,
        acceptance="accepted",
    )
    return Document(
        doc_id=Path(path).stem,
        title=Path(path).stem,
        content="Required phrase and useful body text.",
        space="eval",
        address=path,
        last_updated="2026-09-21T00:00:00+00:00",
        content_blocks=[
            ContentBlock(
                block_type=BlockType.PARAGRAPH,
                text="Required phrase and useful body text.",
                block_id="b1",
                page_number=1,
                bbox=BoundingBox(x0=10, y0=90, x1=200, y1=120),
            ),
            ContentBlock(block_type=BlockType.TABLE, block_id="t1", table=table),
        ],
        parse_diagnostics=ParseDiagnostics(
            parser_name="pdf",
            page_count=1,
            accepted_tables=1,
        ),
    )


def test_discover_pdfs_is_recursive_deduplicated_and_sorted(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    first = tmp_path / "b.pdf"
    second = nested / "a.PDF"
    ignored = tmp_path / "notes.txt"
    first.write_bytes(b"pdf")
    second.write_bytes(b"pdf")
    ignored.write_text("ignore", encoding="utf-8")

    found = discover_pdfs([str(tmp_path), str(first)])

    assert found == sorted([first.resolve(), second.resolve()], key=lambda path: path.as_posix().casefold())


def test_evaluate_paths_aggregates_metrics_expectations_and_parse_failures(tmp_path):
    good = tmp_path / "good.pdf"
    broken = tmp_path / "broken.pdf"
    good.write_bytes(b"pdf")
    broken.write_bytes(b"pdf")
    expectations = {
        "good.pdf": {
            "required_text": ["Required phrase"],
            "forbidden_text": ["forbidden"],
            "min_content_blocks": 2,
            "min_accepted_tables": 1,
        },
    }

    report = evaluate_paths(
        [str(tmp_path)],
        expectations=expectations,
        parser=parsed_document,
    )

    assert report["summary"] == {
        "files": 2,
        "parsed": 1,
        "failed": 1,
        "expectation_failures": 0,
        "content_characters": 37,
        "content_blocks": 2,
        "chunks": 2,
        "accepted_tables": 1,
        "review_tables": 0,
        "ocr_applied_pages": 0,
    }
    good_result = next(item for item in report["files"] if item["name"] == "good.pdf")
    broken_result = next(item for item in report["files"] if item["name"] == "broken.pdf")
    assert good_result["status"] == "ok"
    assert good_result["expectations"]["passed"] is True
    assert good_result["page_region_count"] == 2
    assert good_result["located_chunk_ratio"] == 1.0
    assert broken_result["status"] == "error"
    assert "cannot parse" in broken_result["error"]


def test_evaluate_paths_reports_expectation_failures(tmp_path):
    source = tmp_path / "good.pdf"
    source.write_bytes(b"pdf")

    report = evaluate_paths(
        [str(source)],
        expectations={"good.pdf": {"required_text": ["missing"]}},
        parser=parsed_document,
    )

    assert report["summary"]["expectation_failures"] == 1
    assert report["files"][0]["expectations"] == {
        "passed": False,
        "failures": ["required_text missing: missing"],
    }


def test_evaluate_paths_matches_expectations_by_relative_path(tmp_path):
    first = tmp_path / "first" / "report.pdf"
    second = tmp_path / "second" / "report.pdf"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"pdf")
    second.write_bytes(b"pdf")

    report = evaluate_paths(
        [str(tmp_path)],
        expectations={"second/report.pdf": {"required_text": ["missing"]}},
        parser=parsed_document,
    )

    first_result, second_result = report["files"]
    assert first_result["expectations"] is None
    assert second_result["expectations"]["passed"] is False
