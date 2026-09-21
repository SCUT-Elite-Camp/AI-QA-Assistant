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
    PageRegion,
    TableArtifact,
    TableCell,
)


def test_page_region_normalizes_ids_sources_and_round_trips():
    region = PageRegion(
        page_number=2,
        bbox=BoundingBox(x0=10, y0=20, x1=80, y1=40),
        block_ids=["b2", "", "b2", "b3"],
        table_ids=["t1", "t1"],
        sources=["native", "ocr", "native"],
        confidence=0.75,
    )

    restored = PageRegion.model_validate_json(region.model_dump_json())

    assert restored.block_ids == ["b2", "b3"]
    assert restored.table_ids == ["t1"]
    assert restored.sources == ["native", "ocr"]
    assert restored == region


def test_legacy_single_page_models_derive_one_region():
    bbox = BoundingBox(x0=1, y0=2, x1=30, y1=40)
    chunk = Chunk(index=0, text="text", chunk_id="c1", page_number=3, bbox=bbox)
    table = TableArtifact(
        table_id="t1",
        row_count=0,
        column_count=0,
        page_number=3,
        bbox=bbox,
        parser_name="test",
        confidence=0.9,
        acceptance="accepted",
    )

    assert chunk.page_regions == [PageRegion(
        page_number=3,
        bbox=bbox,
        sources=["native"],
        confidence=1.0,
    )]
    assert table.page_regions[0].page_number == 3
    assert table.page_regions[0].table_ids == ["t1"]


def test_cross_page_chunk_clears_scalar_geometry_but_keeps_all_source_pages():
    regions = [
        PageRegion(
            page_number=2,
            bbox=BoundingBox(x0=1, y0=2, x1=10, y1=20),
            block_ids=["b2"],
        ),
        PageRegion(
            page_number=3,
            bbox=BoundingBox(x0=2, y0=3, x1=11, y1=21),
            block_ids=["b3"],
        ),
    ]
    chunk = Chunk(
        index=0,
        text="cross page",
        chunk_id="c1",
        page_number=2,
        bbox=regions[0].bbox,
        source_pages=[1],
        page_regions=regions,
    )

    assert chunk.source_pages == [1, 2, 3]
    assert chunk.page_number is None
    assert chunk.bbox is None


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
