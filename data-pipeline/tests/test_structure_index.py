from models.document import BlockType, Chunk, ContentBlock, Document
from pipeline.structure import build_document_sections


def test_enterprise_sections_map_to_authoritative_chunks():
    document = Document(
        doc_id="doc-1", title="Policy", content="# Scope\nScope text\n# Controls\nRisk control",
        space="kb", address="policy.md", last_updated="2026-01-01T00:00:00Z",
        doc_type="md", version_id="ver-1",
        content_blocks=[
            ContentBlock(block_type=BlockType.HEADING, level=1, text="Scope"),
            ContentBlock(block_type=BlockType.PARAGRAPH, text="Scope text"),
            ContentBlock(block_type=BlockType.HEADING, level=1, text="Controls"),
            ContentBlock(block_type=BlockType.PARAGRAPH, text="Risk control"),
        ],
        chunks=[
            Chunk(index=0, chunk_id="doc-1_chunk_0", text="# Scope\nScope text"),
            Chunk(index=1, chunk_id="doc-1_chunk_1", text="# Controls\nRisk control"),
        ],
    )
    sections = build_document_sections(document)
    assert [item.title for item in sections] == ["Policy", "Scope", "Controls"]
    assert sections[1].evidence_ids == ["doc-1_chunk_0"]
    assert sections[2].evidence_ids == ["doc-1_chunk_1"]


def test_unstructured_document_has_a_low_quality_root():
    document = Document(
        doc_id="doc-2", title="Plain", content="text", space="kb", address="plain.txt",
        last_updated="2026-01-01T00:00:00Z", version_id="ver-2",
        chunks=[Chunk(index=0, chunk_id="doc-2_chunk_0", text="text")],
    )
    sections = build_document_sections(document)
    assert len(sections) == 1
    assert sections[0].quality == "low"


def test_multiple_headings_in_one_chunk_share_authoritative_evidence():
    document = Document(
        doc_id="doc-3", title="Compact", content="# A\ntext\n## B\nmore",
        space="kb", address="compact.md", last_updated="2026-01-01T00:00:00Z",
        version_id="ver-3",
        content_blocks=[
            ContentBlock(block_type=BlockType.HEADING, level=1, text="A"),
            ContentBlock(block_type=BlockType.PARAGRAPH, text="text"),
            ContentBlock(block_type=BlockType.HEADING, level=2, text="B"),
            ContentBlock(block_type=BlockType.PARAGRAPH, text="more"),
        ],
        chunks=[Chunk(index=0, chunk_id="doc-3_chunk_0", text="# A\ntext\n## B\nmore")],
    )
    sections = build_document_sections(document)
    assert sections[1].evidence_ids == ["doc-3_chunk_0"]
    assert sections[2].evidence_ids == ["doc-3_chunk_0"]
