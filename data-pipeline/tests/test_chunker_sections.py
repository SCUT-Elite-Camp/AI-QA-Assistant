from __future__ import annotations

from models.document import BlockType, ContentBlock
from pipeline.chunker import chunk_from_blocks


def _block(block_type: BlockType, text: str, *, level: int = 0) -> ContentBlock:
    return ContentBlock(block_type=block_type, text=text, level=level)


def test_heading_boundary_prevents_cross_section_evidence() -> None:
    chunks = chunk_from_blocks(
        [
            _block(BlockType.HEADING, "Agent Layer", level=1),
            _block(BlockType.PARAGRAPH, "Planning and tool routing."),
            _block(BlockType.HEADING, "Memory Layer", level=1),
            _block(BlockType.PARAGRAPH, "Long-term memory and recall."),
        ],
        "doc",
        chunk_size=1_000,
        overlap=100,
    )

    assert len(chunks) == 2
    assert chunks[0].section_path == ["Agent Layer"]
    assert chunks[1].section_path == ["Memory Layer"]
    assert "Memory Layer" not in chunks[0].text
    assert "Planning" not in chunks[1].text


def test_long_prose_chunks_keep_the_same_section_path() -> None:
    chunks = chunk_from_blocks(
        [
            _block(BlockType.HEADING, "Implementation", level=2),
            _block(BlockType.PARAGRAPH, "detail " * 100),
        ],
        "doc",
        chunk_size=80,
        overlap=10,
    )

    assert len(chunks) > 2
    assert all(chunk.section_path == ["Implementation"] for chunk in chunks)
    assert all(chunk.block_start is not None and chunk.block_end is not None for chunk in chunks)
