import sys
from pathlib import Path


PIPELINE_ROOT = Path(__file__).resolve().parents[1]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

from models.document import BlockType, ContentBlock, TableArtifact, TableCell  # noqa: E402
from pipeline.chunker import chunk_from_blocks  # noqa: E402


def test_chunker_emits_table_and_header_aware_row_chunks():
    artifact = TableArtifact(
        table_id="sales",
        caption="销售表",
        cells=[
            TableCell(row_index=0, column_index=0, text="地区", is_header=True),
            TableCell(row_index=0, column_index=1, text="金额", is_header=True),
            TableCell(row_index=1, column_index=0, text="华南"),
            TableCell(row_index=1, column_index=1, text="120"),
            TableCell(row_index=2, column_index=0, text="华东"),
            TableCell(row_index=2, column_index=1, text="136"),
        ],
        row_count=3,
        column_count=2,
        header_row_count=1,
        parser_name="test",
        confidence=0.9,
        acceptance="accepted",
    )

    chunks = chunk_from_blocks(
        [ContentBlock(block_type=BlockType.TABLE, table=artifact)],
        "document",
    )

    assert [chunk.chunk_type for chunk in chunks] == ["table", "table_row", "table_row"]
    assert all(chunk.table_id == "sales" for chunk in chunks)
    assert chunks[1].text == "表格：销售表\n地区: 华南 | 金额: 120"
    assert chunks[2].text == "表格：销售表\n地区: 华东 | 金额: 136"


def test_chunker_does_not_index_review_table_cells():
    artifact = TableArtifact(
        table_id="uncertain",
        cells=[TableCell(row_index=0, column_index=0, text="possibly wrong")],
        row_count=1,
        column_count=1,
        parser_name="ocr",
        confidence=0.6,
        acceptance="review",
    )

    chunks = chunk_from_blocks(
        [ContentBlock(block_type=BlockType.TABLE, table=artifact)],
        "document",
    )

    assert chunks == []
