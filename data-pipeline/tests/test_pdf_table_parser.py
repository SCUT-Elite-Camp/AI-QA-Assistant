import sys
import types
from pathlib import Path

import pymupdf as fitz


PIPELINE_ROOT = Path(__file__).resolve().parents[1]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

from models.document import BlockType, BoundingBox, TableArtifact, TableCell  # noqa: E402
from parsers.pdf_parser import PDFParser, _overlap_ratio, _stitch_cross_page_tables  # noqa: E402
from parsers.table_backends import (  # noqa: E402
    CamelotTableBackend,
    GMFTTableBackend,
    PaddleOCRTableBackend,
    PyMuPDFTableBackend,
    _parse_html_table,
)


class StaticRouter:
    def __init__(self, artifacts):
        self.artifacts = artifacts
        self.calls = []

    def route_page(self, page, *, page_number, text_coverage, file_path=None):
        self.calls.append((page_number, text_coverage, file_path))
        return self.artifacts


def make_pdf(path):
    document = fitz.open()
    page = document.new_page(width=500, height=600)
    page.insert_text((60, 200), "candidate text", fontsize=12)
    page.insert_text((60, 400), "ordinary text", fontsize=12)
    document.save(path)
    document.close()


def accepted_artifact():
    return TableArtifact(
        table_id="page-1-table-1",
        cells=[
            TableCell(row_index=0, column_index=0, text="Name", is_header=True),
            TableCell(row_index=1, column_index=0, text="Alice"),
        ],
        row_count=2,
        column_count=1,
        header_row_count=1,
        page_number=1,
        bbox=BoundingBox(x0=40, y0=170, x1=220, y1=230),
        parser_name="test",
        confidence=0.9,
        backend_confidence=0.9,
        quality_score=0.9,
        acceptance="accepted",
    )


def test_rejected_table_candidate_does_not_remove_page_text(tmp_path):
    source = tmp_path / "rejected.pdf"
    make_pdf(source)
    parser = PDFParser(router=StaticRouter([]))

    document = parser.parse(str(source))

    assert "candidate text" in document.content
    assert "ordinary text" in document.content
    assert not any(block.block_type == BlockType.TABLE for block in document.content_blocks)


def test_default_router_keeps_text_when_no_backend_accepts_a_table(tmp_path):
    source = tmp_path / "plain.pdf"
    make_pdf(source)

    document = PDFParser().parse(str(source))

    assert "candidate text" in document.content
    assert "ordinary text" in document.content
    assert not any(block.block_type == BlockType.TABLE for block in document.content_blocks)


def test_accepted_table_excludes_only_overlapping_text_and_keeps_provenance(tmp_path):
    source = tmp_path / "accepted.pdf"
    make_pdf(source)
    router = StaticRouter([accepted_artifact()])
    parser = PDFParser(router=router)

    document = parser.parse(str(source))

    assert "candidate text" not in document.content
    assert "ordinary text" in document.content
    assert "Alice" in document.content
    table_blocks = [block for block in document.content_blocks if block.block_type == BlockType.TABLE]
    assert len(table_blocks) == 1
    table_block = table_blocks[0]
    assert table_block.table.page_number == 1
    assert table_block.table.parser_name == "test"
    assert table_block.block_id == "page-1-table-1"
    assert table_block.page_number == 1
    assert table_block.bbox == table_block.table.bbox
    assert table_block.confidence == 0.9
    assert table_block.source == "table"
    assert table_block.extraction_method == "test"
    assert router.calls[0][0] == 1
    assert router.calls[0][2] == str(source)


def test_accepted_table_keeps_text_when_overlap_is_less_than_half(tmp_path):
    source = tmp_path / "partial-overlap.pdf"
    make_pdf(source)
    artifact = accepted_artifact().model_copy(update={
        "bbox": BoundingBox(x0=40, y0=170, x1=75, y1=230),
    })

    document = PDFParser(router=StaticRouter([artifact])).parse(str(source))

    assert "candidate text" in document.content
    assert _overlap_ratio((60, 188, 140, 204), (40, 170, 75, 230)) < 0.50


def test_review_table_keeps_overlapping_source_text(tmp_path):
    source = tmp_path / "review.pdf"
    make_pdf(source)
    artifact = accepted_artifact().model_copy(update={
        "acceptance": "review",
        "warnings": ["needs_review"],
    })
    parser = PDFParser(router=StaticRouter([artifact]))

    document = parser.parse(str(source))

    assert "candidate text" in document.content
    table = next(block.table for block in document.content_blocks if block.table is not None)
    assert table.acceptance == "review"
    assert "needs_review" in table.warnings
    assert "Alice" not in document.content


def test_optional_backends_report_unavailable_without_importing_heavy_packages(monkeypatch):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)

    assert CamelotTableBackend().available() is False
    assert GMFTTableBackend().available() is False
    assert PaddleOCRTableBackend().available() is False


def test_gmft_backend_normalizes_dataframe_bbox_and_detector_confidence(monkeypatch):
    class FakeValues:
        def tolist(self):
            return [["Name", "Value"], ["Alice", "10"]]

    class FakeFrame:
        values = FakeValues()
        columns = ["Name", "Value"]

        def fillna(self, value):
            return self

        def astype(self, value):
            return self

    class FakeFormatted:
        def df(self):
            return FakeFrame()

    class FakeTable:
        bbox = (50, 100, 350, 300)
        confidence_score = 0.93

    class FakeDetector:
        def extract(self, page):
            return [FakeTable()]

    class FakeFormatter:
        def extract(self, table):
            return FakeFormatted()

    class FakeDocument:
        closed = False

        def __init__(self, path):
            self.pages = [object()]

        def __getitem__(self, index):
            return self.pages[index]

        def close(self):
            self.closed = True

    fake_auto = types.SimpleNamespace(
        AutoTableDetector=FakeDetector,
        AutoTableFormatter=FakeFormatter,
    )
    fake_bindings = types.SimpleNamespace(PyPDFium2Document=FakeDocument)
    monkeypatch.setitem(sys.modules, "gmft.auto", fake_auto)
    monkeypatch.setitem(sys.modules, "gmft.pdf_bindings", fake_bindings)

    artifacts = GMFTTableBackend().extract(object(), 1, "source.pdf")

    assert len(artifacts) == 1
    assert artifacts[0].to_matrix() == [["Name", "Value"], ["Alice", "10"]]
    assert artifacts[0].bbox.model_dump() == {
        "x0": 50.0,
        "y0": 100.0,
        "x1": 350.0,
        "y1": 300.0,
    }
    assert artifacts[0].confidence == 0.93
    assert artifacts[0].parser_name == "gmft:tatr"


def test_gmft_backend_skips_prose_and_detects_repeated_column_alignment():
    backend = GMFTTableBackend()

    class FakePage:
        def __init__(self, words):
            self.words = words

        def get_text(self, kind):
            assert kind == "words"
            return self.words

    prose = [
        (20, row * 20, 50, row * 20 + 10, f"line-{row}", row, 0, 0)
        for row in range(6)
    ]
    grid = [
        (column * 100 + 20, row * 20, column * 100 + 60, row * 20 + 10,
         f"{row}-{column}", row, 0, column)
        for row in range(3)
        for column in range(2)
    ]

    assert backend.should_run(FakePage(prose)) is False
    assert backend.should_run(FakePage(grid)) is True


def test_pymupdf_backend_normalizes_finder_output():
    class FakeTable:
        bbox = (50, 100, 350, 300)

        def extract(self):
            return [["Name", "Value"], ["Alice", "10"]]

    class FakeFinder:
        tables = [FakeTable()]

    class FakePage:
        def find_tables(self):
            return FakeFinder()

    artifacts = PyMuPDFTableBackend().extract(FakePage(), 1, "source.pdf")

    assert len(artifacts) == 1
    assert artifacts[0].to_matrix() == [["Name", "Value"], ["Alice", "10"]]
    assert artifacts[0].bbox is not None
    assert artifacts[0].parser_name == "pymupdf"


def test_pymupdf_backend_uses_builtin_finder_when_layout_extra_is_missing(tmp_path):
    source = tmp_path / "ruled.pdf"
    document = fitz.open()
    page = document.new_page(width=400, height=400)
    for rect in (
        (50, 100, 200, 200),
        (200, 100, 350, 200),
        (50, 200, 200, 300),
        (200, 200, 350, 300),
    ):
        page.draw_rect(rect, color=(0, 0, 0), width=1)
    page.insert_text((80, 150), "Name")
    page.insert_text((230, 150), "Value")
    page.insert_text((80, 250), "Alice")
    page.insert_text((230, 250), "10")
    document.save(source)
    document.close()

    opened = fitz.open(source)
    try:
        artifacts = PyMuPDFTableBackend().extract(opened[0], 1, str(source))
    finally:
        opened.close()

    assert len(artifacts) == 1
    assert artifacts[0].to_matrix() == [["Name", "Value"], ["Alice", "10"]]


def test_paddle_html_normalizer_preserves_row_and_column_spans():
    parsed = _parse_html_table(
        "<table><tr><th rowspan='2'>Region</th><th colspan='2'>Sales</th></tr>"
        "<tr><th>Q1</th><th>Q2</th></tr><tr><td>South</td><td>120</td><td>136</td></tr></table>"
    )

    cells, row_count, column_count = parsed
    assert (row_count, column_count) == (3, 3)
    region = next(cell for cell in cells if cell.text == "Region")
    sales = next(cell for cell in cells if cell.text == "Sales")
    assert (region.row_span, region.column_span) == (2, 1)
    assert (sales.row_span, sales.column_span) == (1, 2)


def test_camelot_backend_normalizes_dataframe_and_pdf_coordinates(monkeypatch):
    class FakeValues:
        def tolist(self):
            return [["Name", "Value"], ["Alice", "10"]]

    class FakeFrame:
        values = FakeValues()

        def fillna(self, value):
            return self

        def astype(self, value):
            return self

    class FakeCamelotTable:
        df = FakeFrame()
        _bbox = (50, 100, 350, 300)
        parsing_report = {"accuracy": 96.0, "whitespace": 5.0}

    fake_module = types.SimpleNamespace(read_pdf=lambda *args, **kwargs: [FakeCamelotTable()])
    monkeypatch.setitem(sys.modules, "camelot", fake_module)

    class FakeRect:
        height = 400

    class FakePage:
        rect = FakeRect()

    artifacts = CamelotTableBackend().extract(FakePage(), 1, "source.pdf")

    assert len(artifacts) == 1
    assert artifacts[0].to_matrix() == [["Name", "Value"], ["Alice", "10"]]
    assert artifacts[0].bbox.model_dump() == {"x0": 50.0, "y0": 100.0, "x1": 350.0, "y1": 300.0}
    assert artifacts[0].parser_name.startswith("camelot:")


def test_cross_page_tables_stitch_only_with_matching_headers_and_edge_positions():
    first = TableArtifact(
        table_id="page-1-table",
        cells=[
            TableCell(row_index=0, column_index=0, text="Name", is_header=True),
            TableCell(row_index=0, column_index=1, text="Value", is_header=True),
            TableCell(row_index=1, column_index=0, text="Alice"),
            TableCell(row_index=1, column_index=1, text="10"),
        ],
        row_count=2,
        column_count=2,
        header_row_count=1,
        page_number=1,
        bbox=BoundingBox(x0=30, y0=700, x1=500, y1=790),
        parser_name="camelot:lattice",
        confidence=0.9,
        backend_confidence=0.92,
        quality_score=0.9,
        acceptance="accepted",
    )
    second = first.model_copy(update={
        "table_id": "page-2-table",
        "page_number": 2,
        "source_pages": [2],
        "source_table_ids": ["page-2-table"],
        "bbox": BoundingBox(x0=30, y0=20, x1=500, y1=160),
        "cells": [
            TableCell(row_index=0, column_index=0, text="Name", is_header=True),
            TableCell(row_index=0, column_index=1, text="Value", is_header=True),
            TableCell(row_index=1, column_index=0, text="Bob"),
            TableCell(row_index=1, column_index=1, text="18"),
        ],
    })

    result = _stitch_cross_page_tables([first, second], {1: 800, 2: 800})

    assert len(result) == 1
    assert result[0].body_rows() == [["Alice", "10"], ["Bob", "18"]]
    assert result[0].source_pages == [1, 2]
    assert result[0].source_table_ids == ["page-1-table", "page-2-table"]
    assert "cross_page_stitched" in result[0].warnings
