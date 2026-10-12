import sys
from pathlib import Path


PIPELINE_ROOT = Path(__file__).resolve().parents[1]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

from models.document import (  # noqa: E402
    BlockType,
    BoundingBox,
    ContentBlock,
    TableArtifact,
    TableCell,
)


def test_table_artifact_expands_spans_and_derives_legacy_rows():
    artifact = TableArtifact(
        table_id="page-1-table-1",
        cells=[
            TableCell(row_index=0, column_index=0, text="地区", row_span=2, is_header=True),
            TableCell(row_index=0, column_index=1, text="2025 销售额", column_span=2, is_header=True),
            TableCell(row_index=1, column_index=1, text="Q1", is_header=True),
            TableCell(row_index=1, column_index=2, text="Q2", is_header=True),
            TableCell(row_index=2, column_index=0, text="华南"),
            TableCell(row_index=2, column_index=1, text="120"),
            TableCell(row_index=2, column_index=2, text="136"),
        ],
        row_count=3,
        column_count=3,
        header_row_count=2,
        parser_name="docx",
        confidence=0.9,
    )

    assert artifact.to_matrix() == [
        ["地区", "2025 销售额", "2025 销售额"],
        ["地区", "Q1", "Q2"],
        ["华南", "120", "136"],
    ]
    assert artifact.legacy_headers() == ["地区", "2025 销售额 / Q1", "2025 销售额 / Q2"]
    assert artifact.body_rows() == [["华南", "120", "136"]]

    block = ContentBlock(block_type=BlockType.TABLE, table=artifact)
    assert block.headers == ["地区", "2025 销售额 / Q1", "2025 销售额 / Q2"]
    assert block.rows == [["华南", "120", "136"]]


def test_table_artifact_markdown_escapes_cell_text_and_keeps_provenance():
    artifact = TableArtifact(
        table_id="page-2-table-1",
        cells=[
            TableCell(row_index=0, column_index=0, text="字段", is_header=True),
            TableCell(row_index=0, column_index=1, text="值", is_header=True),
            TableCell(row_index=1, column_index=0, text="A|B"),
            TableCell(row_index=1, column_index=1, text="第一行\n第二行"),
        ],
        row_count=2,
        column_count=2,
        header_row_count=1,
        page_number=2,
        bbox=BoundingBox(x0=10, y0=20, x1=200, y1=140),
        parser_name="pymupdf",
        confidence=0.82,
        warnings=["low_header_quality"],
    )

    assert artifact.to_markdown() == (
        "| 字段 | 值 |\n"
        "| --- | --- |\n"
        "| A\\|B | 第一行<br>第二行 |"
    )
    assert artifact.page_number == 2
    assert artifact.bbox.x1 == 200
    assert artifact.warnings == ["low_header_quality"]


def test_legacy_table_block_without_artifact_still_renders():
    block = ContentBlock(
        block_type=BlockType.TABLE,
        headers=["名称", "数量"],
        rows=[["A", "2"]],
    )

    assert block.table is None
    assert block.to_markdown() == "| 名称 | 数量 |\n| --- | --- |\n| A | 2 |"


def test_review_table_block_is_excluded_from_index_rendering():
    artifact = TableArtifact(
        table_id="review-table",
        cells=[
            TableCell(row_index=0, column_index=0, text="字段", is_header=True),
            TableCell(row_index=1, column_index=0, text="候选值"),
        ],
        row_count=2,
        column_count=1,
        header_row_count=1,
        parser_name="pymupdf",
        confidence=0.4,
        acceptance="review",
    )

    block = ContentBlock(block_type=BlockType.TABLE, table=artifact)

    assert block.is_indexable is False
    assert block.to_index_markdown() == ""


def test_header_only_table_is_not_silently_dropped():
    artifact = TableArtifact(
        table_id="header-only",
        cells=[
            TableCell(row_index=0, column_index=0, text="字段", is_header=True),
            TableCell(row_index=0, column_index=1, text="说明", is_header=True),
        ],
        row_count=1,
        column_count=2,
        header_row_count=1,
        parser_name="docx",
        confidence=0.9,
    )

    assert artifact.to_markdown() == "| 字段 | 说明 |\n| --- | --- |"


def test_table_artifact_exports_canonical_html_and_header_aware_row_chunks():
    artifact = TableArtifact(
        table_id="merged-table",
        cells=[
            TableCell(row_index=0, column_index=0, text="地区", row_span=2, is_header=True),
            TableCell(row_index=0, column_index=1, text="销售额", column_span=2, is_header=True),
            TableCell(row_index=1, column_index=1, text="Q1", is_header=True),
            TableCell(row_index=1, column_index=2, text="Q2", is_header=True),
            TableCell(row_index=2, column_index=0, text="华南"),
            TableCell(row_index=2, column_index=1, text="120"),
            TableCell(row_index=2, column_index=2, text="136"),
        ],
        row_count=3,
        column_count=3,
        header_row_count=2,
        parser_name="docx",
        confidence=0.95,
    )

    html = artifact.to_html()
    assert 'rowspan="2"' in html
    assert 'colspan="2"' in html
    assert "<th" in html
    assert artifact.to_row_chunks() == [
        "地区: 华南 | 销售额 / Q1: 120 | 销售额 / Q2: 136"
    ]
