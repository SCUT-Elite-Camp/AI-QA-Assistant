from __future__ import annotations

import pytest

from models.document import BlockType, Chunk, ContentBlock, Document, DocumentSection
from pipeline.chunker import chunk_from_blocks, split_prose_at_boundaries
from pipeline.structure import build_document_sections
from pipeline.wiki.chunker import build_wiki_chunks


def _document(title: str, blocks: list[ContentBlock], *, size: int = 500) -> Document:
    document = Document(
        doc_id="doc", version_id="ver", title=title, content="", space="RAG",
        address="", last_updated="", content_blocks=blocks,
    )
    document.chunks = chunk_from_blocks(blocks, "ver", chunk_size=size,
                                        overlap=50, document_title=title)
    document.sections = build_document_sections(document)
    return document


def test_oversize_prose_keeps_complete_sentences_and_no_duplicate_overlap() -> None:
    text = "First complete sentence. " * 20
    parts = split_prose_at_boundaries(text, 80)
    assert "".join(parts) == text
    assert all(part.rstrip().endswith(".") for part in parts)
    document = _document("Meeting Minutes", [
        ContentBlock(block_type=BlockType.HEADING, text="Agenda", level=1),
        ContentBlock(block_type=BlockType.PARAGRAPH, text=text),
    ], size=80)
    assert all(chunk.overlap_prefix_length == 0 for chunk in document.chunks)
    assert "".join(chunk.text.removeprefix("# Agenda\n\n") for chunk in document.chunks) == text


def test_wiki_chunks_are_source_bound_and_preserve_section_and_order() -> None:
    document = _document("Meeting Minutes", [
        ContentBlock(block_type=BlockType.HEADING, text="Agent", level=1),
        ContentBlock(block_type=BlockType.PARAGRAPH, text="Agent planning is complete. The next step is testing.",
                     locator={"line_start": 3, "line_end": 3}),
        ContentBlock(block_type=BlockType.HEADING, text="Memory", level=1),
        ContentBlock(block_type=BlockType.PARAGRAPH, text="Memory remains pending.",
                     locator={"line_start": 6, "line_end": 6}),
    ], size=500)
    chunks = build_wiki_chunks(document)
    assert len(chunks) == 2
    assert chunks[0].heading_path[-1] == "Agent"
    assert chunks[1].heading_path[-1] == "Memory"
    assert chunks[0].next_chunk_id == chunks[1].id
    assert chunks[1].prev_chunk_id == chunks[0].id
    evidence = {item.chunk_id: item for item in document.chunks}
    for chunk in chunks:
        for span in chunk.source_spans:
            assert chunk.content[span.chunk_start:span.chunk_end] == evidence[span.evidence_id].text[
                span.evidence_start:span.evidence_end]
    assert build_wiki_chunks(document) == chunks


def test_table_and_list_are_atomic_even_when_oversized() -> None:
    document = _document("Architecture", [
        ContentBlock(block_type=BlockType.HEADING, text="Results", level=1),
        ContentBlock(block_type=BlockType.TABLE, headers=["name", "value"],
                     rows=[["A", "1"]] * 20),
        ContentBlock(block_type=BlockType.LIST, text="A complete action item."),
    ], size=80)
    chunks = build_wiki_chunks(document, max_chars=80)
    assert [chunk.content_type for chunk in chunks] == ["table", "list"]
    assert chunks[0].content.count("| A | 1 |") == 20


def test_wiki_builder_discards_retrieval_overlap_not_source_content() -> None:
    document = Document(doc_id="doc", version_id="ver", title="Notes", content="",
                        space="RAG", address="", last_updated="", chunks=[
        Chunk(index=0, chunk_id="ev1", text="First paragraph."),
        Chunk(index=1, chunk_id="ev2", text="paragraph.\n\nSecond paragraph.",
              overlap_prefix_length=len("paragraph.\n\n")),
    ])
    chunks = build_wiki_chunks(document)
    assert "Second paragraph." in " ".join(chunk.content for chunk in chunks)
    assert sum(chunk.content.count("paragraph.") for chunk in chunks) == 2
    assert all(span.evidence_start >= 0 for chunk in chunks for span in chunk.source_spans)


def test_boundary_reviewer_can_only_split_at_source_spans() -> None:
    document = Document(doc_id="doc", version_id="ver", title="Notes", content="",
                        space="RAG", address="", last_updated="", chunks=[
        Chunk(index=0, chunk_id="ev1", text="First paragraph."),
        Chunk(index=1, chunk_id="ev2", text="Second paragraph."),
    ])
    chunks = build_wiki_chunks(document, boundary_reviewer=lambda _text, parts: [len(parts[0])])
    assert [chunk.content for chunk in chunks] == ["First paragraph.", "Second paragraph."]
    with pytest.raises(ValueError, match="existing source boundaries"):
        build_wiki_chunks(document, boundary_reviewer=lambda _text, _parts: [5])


def test_section_selection_uses_heading_path_not_incidental_evidence_membership() -> None:
    document = Document(
        doc_id="doc", version_id="ver", title="Notes", content="",
        space="RAG", address="", last_updated="",
        chunks=[Chunk(index=0, chunk_id="ev", text="# Agent\n\nAgent details.",
                      section_path=["Notes", "Agent"])],
        sections=[
            DocumentSection(id="root", version_id="ver", title="Notes", level=0,
                            section_path=["Notes"], evidence_ids=["ev"]),
            DocumentSection(id="agent", version_id="ver", title="Agent", level=1,
                            section_path=["Notes", "Agent"], evidence_ids=["ev"]),
            DocumentSection(id="wrong", version_id="ver", title="Memory", level=2,
                            section_path=["Notes", "Memory"], evidence_ids=["ev"]),
        ],
    )
    chunks = build_wiki_chunks(document)
    assert len(chunks) == 1
    assert chunks[0].section_id == "agent"
    assert chunks[0].heading_path == ["Notes", "Agent"]
    assert chunks[0].content == "Agent details."


def test_mixed_prose_table_and_list_keep_distinct_content_types() -> None:
    document = _document("Architecture", [
        ContentBlock(block_type=BlockType.HEADING, text="Results", level=1),
        ContentBlock(block_type=BlockType.PARAGRAPH, text="The result is described here."),
        ContentBlock(block_type=BlockType.TABLE, headers=["name", "score"], rows=[["A", "1"]]),
        ContentBlock(block_type=BlockType.LIST, text="Follow-up action."),
    ], size=500)
    chunks = build_wiki_chunks(document)
    assert [chunk.content_type for chunk in chunks] == ["prose", "table", "list"]
    assert chunks[0].content == "The result is described here."
    assert "| A | 1 |" in chunks[1].content
    assert chunks[2].content == "- Follow-up action."
