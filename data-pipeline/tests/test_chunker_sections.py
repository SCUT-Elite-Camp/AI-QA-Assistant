from __future__ import annotations

from models.document import BlockType, ContentBlock
from parsers.markdown_parser import MarkdownParser
from pipeline.chunker import chunk_from_blocks
from pipeline.structure import build_document_sections


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


def test_recovered_bold_headings_are_hard_boundaries_and_map_to_sections() -> None:
    markdown = (
        "# Meeting Minutes\n\n"
        "**Quick Recap**\n\n"
        "The recap discusses schedules and attendance.\n\n"
        "**Agent Layer**\n\n"
        "The agent work includes a mock workflow.\n"
    )
    document = MarkdownParser().parse_text(
        markdown, source="meeting.md", metadata={"title": "Meeting Minutes"},
    )
    document.chunks = chunk_from_blocks(
        document.content_blocks, document.version_id,
        chunk_size=1_000, overlap=100, document_title=document.title,
    )
    document.sections = build_document_sections(document)

    recap = next(section for section in document.sections if section.title == "Quick Recap")
    agent = next(section for section in document.sections if section.title == "Agent Layer")
    assert len(recap.evidence_ids) == len(agent.evidence_ids) == 1
    recap_chunk = next(chunk for chunk in document.chunks if chunk.chunk_id == recap.evidence_ids[0])
    agent_chunk = next(chunk for chunk in document.chunks if chunk.chunk_id == agent.evidence_ids[0])
    assert recap_chunk.section_path == ["Quick Recap"]
    assert agent_chunk.section_path == ["Agent Layer"]
    assert "recap discusses" not in agent_chunk.text
    assert "agent work" not in recap_chunk.text


def test_overlap_never_crosses_recovered_bold_heading() -> None:
    chunks = chunk_from_blocks(
        [
            _block(BlockType.HEADING, "Document", level=1),
            ContentBlock(block_type=BlockType.PARAGRAPH, text="First Section", bold=True),
            _block(BlockType.PARAGRAPH, "RECAP_MARKER " * 20),
            ContentBlock(block_type=BlockType.PARAGRAPH, text="Second Section", bold=True),
            _block(BlockType.PARAGRAPH, "AGENT_MARKER content"),
        ],
        "doc", chunk_size=80, overlap=20, document_title="Document",
    )
    assert any("AGENT_MARKER" in chunk.text for chunk in chunks)
    assert all("RECAP_MARKER" not in chunk.text for chunk in chunks if "AGENT_MARKER" in chunk.text)


def test_bold_fields_do_not_become_boundaries_in_native_heading_documents() -> None:
    chunks = chunk_from_blocks(
        [
            _block(BlockType.HEADING, "Document", level=1),
            _block(BlockType.HEADING, "First", level=2),
            _block(BlockType.PARAGRAPH, "Before the bold field."),
            ContentBlock(block_type=BlockType.PARAGRAPH, text="Authentication required", bold=True),
            _block(BlockType.PARAGRAPH, "After the bold field."),
            _block(BlockType.HEADING, "Second", level=2),
            _block(BlockType.PARAGRAPH, "Next section."),
        ],
        "doc", chunk_size=1_000, overlap=100, document_title="Document",
    )
    first = next(chunk for chunk in chunks if "Before the bold field" in chunk.text)
    assert "After the bold field" in first.text
    assert "Next section" not in first.text


def test_heading_is_attached_to_oversize_first_body_not_emitted_alone() -> None:
    chunks = chunk_from_blocks(
        [
            _block(BlockType.HEADING, "Agent Layer", level=1),
            _block(BlockType.PARAGRAPH, "AGENT_BODY " * 80),
            _block(BlockType.HEADING, "Memory Layer", level=1),
            _block(BlockType.PARAGRAPH, "MEMORY_BODY"),
        ],
        "doc", chunk_size=80, overlap=10,
    )
    assert chunks[0].text.startswith("# Agent Layer\n\nAGENT_BODY")
    assert chunks[0].block_start == 0 and chunks[0].block_end == 1
    assert all(chunk.text.strip() != "# Agent Layer" for chunk in chunks)
    assert all("AGENT_BODY" not in chunk.text for chunk in chunks if "MEMORY_BODY" in chunk.text)


def test_empty_section_has_no_heading_only_evidence() -> None:
    chunks = chunk_from_blocks(
        [
            _block(BlockType.HEADING, "Empty", level=1),
            _block(BlockType.HEADING, "Content", level=1),
            _block(BlockType.PARAGRAPH, "The substantive body."),
        ],
        "doc", chunk_size=80, overlap=10,
    )
    assert len(chunks) == 1
    assert chunks[0].text == "# Content\n\nThe substantive body."


def test_oversize_list_and_code_remain_atomic() -> None:
    long_list = "one complete list item with several details " * 10
    long_code = "def function():\n    return value\n" * 10
    chunks = chunk_from_blocks(
        [
            _block(BlockType.HEADING, "Tasks", level=1),
            _block(BlockType.LIST, long_list),
            ContentBlock(block_type=BlockType.PARAGRAPH, text=long_code,
                         locator={"code": True}),
        ], "doc", chunk_size=80, overlap=10,
    )
    assert len(chunks) == 2
    assert chunks[0].text == "# Tasks\n\n- " + long_list
    assert chunks[1].text == long_code
