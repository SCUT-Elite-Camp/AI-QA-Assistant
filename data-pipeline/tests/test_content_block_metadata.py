import sys
from pathlib import Path


PIPELINE_ROOT = Path(__file__).resolve().parents[1]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

from models.document import (  # noqa: E402
    BlockType,
    BoundingBox,
    Chunk,
    ContentBlock,
    Document,
    TableArtifact,
    TableCell,
)


def make_table(*, acceptance: str) -> TableArtifact:
    return TableArtifact(
        table_id="page-2-table-1",
        cells=[
            TableCell(row_index=0, column_index=0, text="字段", is_header=True),
            TableCell(row_index=1, column_index=0, text="值"),
        ],
        row_count=2,
        column_count=1,
        header_row_count=1,
        page_number=2,
        bbox=BoundingBox(x0=10, y0=20, x1=80, y1=80),
        parser_name="pymupdf",
        confidence=0.95,
        acceptance=acceptance,
    )


def test_content_block_round_trips_pdf_provenance():
    block = ContentBlock(
        block_type=BlockType.PARAGRAPH,
        text="正文",
        block_id="page-2-block-3",
        page_number=2,
        bbox=BoundingBox(x0=10, y0=20, x1=80, y1=40),
        font_name="NotoSansCJK",
        font_size=11.0,
        rotation=0.0,
        confidence=0.95,
        source="native",
        extraction_method="pymupdf",
    )

    assert block.block_id == "page-2-block-3"
    assert block.page_number == 2
    assert block.bbox == BoundingBox(x0=10, y0=20, x1=80, y1=40)
    assert block.font_name == "NotoSansCJK"
    assert block.font_size == 11.0
    assert block.rotation == 0.0
    assert block.confidence == 0.95
    assert block.source == "native"
    assert block.extraction_method == "pymupdf"
    assert ContentBlock.model_validate(block.model_dump()) == block


def test_chunk_round_trips_provenance_and_cross_page_metadata():
    chunk = Chunk(
        index=0,
        text="跨页正文",
        chunk_id="doc_chunk_0",
        block_id="page-2-block-3",
        page_number=None,
        bbox=None,
        source="native",
        source_pages=[2, 3],
        metadata={"source_pages": [2, 3], "quality": "high"},
    )

    assert chunk.block_id == "page-2-block-3"
    assert chunk.source_pages == [2, 3]
    assert chunk.metadata == {"source_pages": [2, 3], "quality": "high"}
    assert Chunk.model_validate(chunk.model_dump()) == chunk


def test_review_table_is_not_indexable():
    block = ContentBlock(
        block_type=BlockType.TABLE,
        table=make_table(acceptance="review"),
    )

    assert block.is_indexable is False
    assert block.to_index_markdown() == ""


def test_document_render_index_content_excludes_review_tables():
    document = Document(
        doc_id="doc",
        title="title",
        content="legacy content",
        space="space",
        address="address",
        last_updated="2026-01-01T00:00:00+00:00",
        content_blocks=[
            ContentBlock(block_type=BlockType.PARAGRAPH, text="正文"),
            ContentBlock(block_type=BlockType.TABLE, table=make_table(acceptance="review")),
            ContentBlock(block_type=BlockType.TABLE, table=make_table(acceptance="accepted")),
        ],
    )

    rendered = document.render_index_content()

    assert "正文" in rendered
    assert "| 字段 |" in rendered
    assert rendered.count("| 字段 |") == 1
