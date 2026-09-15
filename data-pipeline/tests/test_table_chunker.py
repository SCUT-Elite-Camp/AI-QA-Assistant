import sys
from pathlib import Path


PIPELINE_ROOT = Path(__file__).resolve().parents[1]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

from models.document import BoundingBox, BlockType, ContentBlock, TableArtifact, TableCell  # noqa: E402
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


def test_text_chunks_aggregate_same_page_boxes_and_cross_page_sources():
    first = ContentBlock(block_type="paragraph", text="First source block", block_id="b1",
                         page_number=1, bbox=BoundingBox(x0=1, y0=2, x1=10, y1=20))
    second = ContentBlock(block_type="paragraph", text="Second source block", block_id="b2",
                          page_number=1, bbox=BoundingBox(x0=2, y0=30, x1=11, y1=40))
    same = chunk_from_blocks([first, second], "doc", overlap=0)[0]
    assert same.page_number == 1 and same.source_pages == [1]
    assert same.bbox == BoundingBox(x0=1, y0=2, x1=11, y1=40)
    assert same.metadata["block_ids"] == ["b1", "b2"]
    cross = chunk_from_blocks([first, second.model_copy(update={"page_number": 2})], "doc", overlap=0)[0]
    assert cross.page_number is None and cross.bbox is None
    assert cross.source_pages == [1, 2]


def test_overlap_tracks_sources_and_zero_overlap_repeats_no_text():
    blocks = [ContentBlock(block_type="paragraph", text="first source", block_id="b1", page_number=1),
              ContentBlock(block_type="paragraph", text="second source", block_id="b2", page_number=2)]
    chunks = chunk_from_blocks(blocks, "doc", chunk_size=15, overlap=0)
    assert [c.text for c in chunks] == ["first source", "second source"]
    assert [c.page_number for c in chunks] == [1, 2]
    overlapping = chunk_from_blocks(blocks, "doc", chunk_size=15, overlap=6)
    assert overlapping[1].text == "source\n\nsecond source"
    assert overlapping[1].source_pages == [1, 2]
    assert overlapping[1].page_number is None


def test_legacy_table_blocks_remain_first_class_tables():
    chunks = chunk_from_blocks([ContentBlock(block_type="table", headers=["Name"], rows=[["East"]])], "doc")
    assert chunks[0].chunk_type == "table"
    assert "| East |" in chunks[0].text
