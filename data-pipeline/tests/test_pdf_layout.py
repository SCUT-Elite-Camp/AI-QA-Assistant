import math
import sys
from pathlib import Path


PIPELINE_ROOT = Path(__file__).resolve().parents[1]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

from models.document import BlockType  # noqa: E402
from parsers.pdf_layout import (  # noqa: E402
    LayoutBlock,
    extract_layout_blocks,
    filter_repeated_edge_blocks,
    find_repeated_edge_keys,
    normalize_edge_text,
    order_layout_blocks,
)


def layout(
    text,
    x0,
    y0,
    x1,
    y1,
    *,
    page=1,
    ordinal=0,
    page_width=520,
    page_height=700,
    font_size=11.0,
    font_name="Body",
    flags=0,
):
    return LayoutBlock(
        text=text,
        bbox=(x0, y0, x1, y1),
        font_size=font_size,
        font_name=font_name,
        flags=flags,
        rotation=0.0,
        page_number=page,
        ordinal=ordinal,
        page_width=page_width,
        page_height=page_height,
    )


def page_blocks(page, *, header, title):
    blocks = [layout(header, 40, 20, 480, 40, page=page, ordinal=0)]
    if title is not None:
        blocks.append(layout(title, 40, 60, 480, 90, page=page, ordinal=1))
    blocks.append(layout(f"Body {page}", 40, 160, 480, 190, page=page, ordinal=2))
    return blocks


def test_two_column_blocks_read_left_column_before_right_column():
    blocks = [
        layout("L1", 40, 100, 220, 120, ordinal=0),
        layout("R1", 300, 100, 480, 120, ordinal=1),
        layout("L2", 40, 150, 220, 170, ordinal=2),
        layout("R2", 300, 150, 480, 170, ordinal=3),
    ]

    assert [block.text for block in order_layout_blocks(blocks, 520)] == [
        "L1",
        "L2",
        "R1",
        "R2",
    ]


def test_spanning_blocks_partition_two_column_sections():
    blocks = [
        layout("L1", 40, 100, 220, 120, ordinal=0),
        layout("R1", 300, 100, 480, 120, ordinal=1),
        layout("L2", 40, 150, 220, 170, ordinal=2),
        layout("R2", 300, 150, 480, 170, ordinal=3),
        layout("Section", 40, 200, 480, 225, ordinal=4),
        layout("L3", 40, 250, 220, 270, ordinal=5),
        layout("R3", 300, 250, 480, 270, ordinal=6),
        layout("L4", 40, 300, 220, 320, ordinal=7),
        layout("R4", 300, 300, 480, 320, ordinal=8),
    ]

    assert [block.text for block in order_layout_blocks(blocks, 520)] == [
        "L1",
        "L2",
        "R1",
        "R2",
        "Section",
        "L3",
        "L4",
        "R3",
        "R4",
    ]


def test_repeated_header_is_removed_but_single_page_title_is_kept():
    pages = [
        page_blocks(1, header="Company report", title="Annual results"),
        page_blocks(2, header="Company report", title=None),
        page_blocks(3, header="Company report", title=None),
    ]

    keys = find_repeated_edge_keys(pages)
    filtered, diagnostics = filter_repeated_edge_blocks(pages, keys)

    assert normalize_edge_text("Company report") in keys
    assert normalize_edge_text("Annual results") not in keys
    assert [block.text for block in filtered[0]] == ["Annual results", "Body 1"]
    assert diagnostics.removed_headers == 3
    assert diagnostics.removed_footers == 0


def test_page_number_only_edges_share_a_normalized_key():
    pages = [
        [layout(str(page), 250, 670, 270, 690, page=page)]
        for page in range(1, 4)
    ]

    keys = find_repeated_edge_keys(pages)

    assert normalize_edge_text("1") == normalize_edge_text("99")
    assert normalize_edge_text("1") in keys


def test_repeated_text_is_removed_only_from_its_matching_edge_band():
    pages = [
        [layout("Confidential", 40, 20, 180, 40, page=1)],
        [layout("Confidential", 40, 20, 180, 40, page=2)],
        [layout("Confidential", 40, 660, 180, 680, page=3)],
    ]

    filtered, diagnostics = filter_repeated_edge_blocks(pages)

    assert [block.text for block in filtered[0]] == []
    assert [block.text for block in filtered[1]] == []
    assert [block.text for block in filtered[2]] == ["Confidential"]
    assert diagnostics.removed_headers == 2
    assert diagnostics.removed_footers == 0


class FakeRect:
    width = 500
    height = 700


class FakePage:
    rect = FakeRect()

    def get_text(self, mode, *, sort):
        assert (mode, sort) == ("dict", False)
        return {
            "blocks": [
                {
                    "type": 0,
                    "bbox": (40, 100, 300, 145),
                    "lines": [
                        {
                            "dir": (0.0, -1.0),
                            "spans": [
                                {"text": "Layout ", "size": 12, "font": "Body", "flags": 0},
                                {"text": "heading", "size": 18, "font": "Display", "flags": 16},
                            ],
                        },
                        {
                            "dir": (0.0, -1.0),
                            "spans": [
                                {"text": "continues", "size": 12, "font": "Body", "flags": 0},
                            ],
                        },
                    ],
                },
                {"type": 1, "bbox": (0, 0, 10, 10), "lines": []},
            ]
        }


def test_extract_layout_blocks_preserves_text_style_direction_and_provenance():
    blocks = extract_layout_blocks(FakePage(), page_number=4)

    assert len(blocks) == 1
    block = blocks[0]
    assert block.text == "Layout heading\ncontinues"
    assert block.font_name == "Body"
    assert block.font_size == 18
    assert block.flags == 16
    assert math.isclose(block.rotation, -90.0)

    content = block.to_content_block()
    assert content.block_id == "page-4-block-0"
    assert content.page_number == 4
    assert content.bbox.model_dump() == {"x0": 40.0, "y0": 100.0, "x1": 300.0, "y1": 145.0}
    assert content.font_name == "Body"
    assert content.font_size == 18
    assert content.rotation == -90.0
    assert content.confidence == 1.0
    assert content.source == "native"
    assert content.extraction_method == "pymupdf"


def test_large_non_bold_font_is_preserved_as_heading_candidate(tmp_path):
    import pymupdf as fitz

    from parsers.pdf_parser import PDFParser

    source = tmp_path / "heading.pdf"
    document = fitz.open()
    page = document.new_page(width=500, height=700)
    page.insert_text((60, 100), "Annual results", fontsize=16)
    page.insert_text((60, 160), "First body paragraph", fontsize=10)
    page.insert_text((60, 200), "Second body paragraph", fontsize=10)
    document.save(source)
    document.close()

    parsed = PDFParser(router=StaticRouter()).parse(str(source))

    heading = next(block for block in parsed.content_blocks if block.text == "Annual results")
    assert heading.block_type == BlockType.HEADING
    assert heading.level == 1
    assert heading.block_id == "page-1-block-0"
    assert heading.page_number == 1
    assert heading.bbox is not None
    assert heading.font_size == 16
    assert heading.extraction_method == "pymupdf"
    assert parsed.title == "heading"
    assert parsed.content.startswith("# Annual results")


def test_pdf_parser_uses_column_order_and_dynamic_edge_filtering(tmp_path):
    import pymupdf as fitz

    from parsers.pdf_parser import PDFParser

    source = tmp_path / "columns.pdf"
    document = fitz.open()
    for page_number in range(1, 4):
        page = document.new_page(width=520, height=700)
        page.insert_text((40, 30), "Company report", fontsize=9)
        if page_number == 1:
            page.insert_text((40, 70), "Annual results", fontsize=14)
        page.insert_textbox((40, 105, 220, 135), f"L1 page {page_number}", fontsize=10)
        page.insert_textbox((300, 105, 480, 135), f"R1 page {page_number}", fontsize=10)
        page.insert_textbox((40, 155, 220, 185), f"L2 page {page_number}", fontsize=10)
        page.insert_textbox((300, 155, 480, 185), f"R2 page {page_number}", fontsize=10)
    document.save(source)
    document.close()

    parser = PDFParser(router=StaticRouter())
    parsed = parser.parse(str(source))

    assert "Company report" not in parsed.content
    assert "Annual results" in parsed.content
    assert parsed.content.index("L2 page 1") < parsed.content.index("R1 page 1")
    assert parser.last_layout_diagnostics.removed_headers == 3


class StaticRouter:
    def route_page(self, page, *, page_number, text_coverage, file_path=None):
        return []
