import json

import pytest

from models.document import BlockType, BoundingBox, ContentBlock, Document, PageRegion, TableArtifact, TableCell
from pipeline import auto_process
from pipeline.structured_ingestion import prepare_ingestion_chunks, provenance_columns
from pipeline.structure import build_document_sections
from pipeline.wiki.chunker import build_wiki_chunks
from parsers.registry import DocumentParser


def table_document():
    artifact = TableArtifact(
        table_id="sales", row_count=2, column_count=2, header_row_count=1,
        acceptance="accepted", parser_name="native", confidence=1.0,
        cells=[
            TableCell(row_index=0, column_index=0, text="Region", is_header=True),
            TableCell(row_index=0, column_index=1, text="Revenue", is_header=True),
            TableCell(row_index=1, column_index=0, text="South"),
            TableCell(row_index=1, column_index=1, text="120"),
        ],
        page_regions=[PageRegion(
            page_number=2, bbox=BoundingBox(x0=10, y0=20, x1=90, y1=100),
            table_ids=["sales"], sources=["table"],
        )],
    )
    block = ContentBlock(block_type=BlockType.TABLE, table=artifact)
    return Document(
        doc_id="doc", title="Sales", content=block.to_markdown(),
        space="test", address="", last_updated="1", version_id="v1",
        content_blocks=[block],
    )


class FakeStore:
    def __init__(self, name, *, schema_valid=True):
        self.collection_name = name
        self.collection = self
        self.schema_valid = schema_valid
        self.deletes = []
        self.rows = None

    def init_collection(self, **kwargs):
        return self

    def connect(self):
        pass

    def validate_chunk_schema(self):
        if not self.schema_valid:
            raise ValueError("missing provenance schema")

    def delete(self, expr):
        self.deletes.append(expr)

    def flush(self):
        pass

    def insert_chunks(self, **rows):
        self.rows = rows


def test_ingestion_embeds_semantic_text_and_persists_display_and_geometry(monkeypatch):
    evidence, sections = FakeStore("evidence"), FakeStore("sections")
    embedded, saved = [], []
    monkeypatch.setattr(auto_process, "embed_texts", lambda texts: (
        embedded.append(texts) or [[1.0, 0.0] for _ in texts]
    ))
    monkeypatch.setattr(auto_process, "save_document", lambda *args: saved.append(args))
    monkeypatch.setenv("WIKI_INGEST_ENABLED", "false")
    document = table_document()

    assert auto_process._index_document(
        document, chunk_size=500, overlap=0, evidence_milvus=evidence,
        section_milvus=sections, has_milvus=True,
    )
    assert embedded[0] == [chunk.index_text for chunk in document.chunks]
    assert evidence.rows["chunk_texts"][0] == document.content
    assert evidence.rows["chunk_types"] == ["table", "table_row"]
    metadata = json.loads(evidence.rows["metadata_jsons"][0])
    assert metadata["page_regions"][0]["bbox"] == [10, 20, 90, 100]
    assert metadata["source_pages"] == [2]
    assert saved[0][1]["chunks"][0]["page_regions"][0]["page_number"] == 2


def test_incompatible_schema_stops_before_deleting_either_index(monkeypatch):
    evidence, sections = FakeStore("evidence", schema_valid=False), FakeStore("sections")
    monkeypatch.setattr(auto_process, "embed_texts", lambda texts: [[1.0] for _ in texts])
    monkeypatch.setattr(auto_process, "save_document", lambda *args: pytest.fail("must not save"))
    with pytest.raises(ValueError, match="missing provenance"):
        auto_process._index_document(
            table_document(), chunk_size=500, overlap=0, evidence_milvus=evidence,
            section_milvus=sections, has_milvus=True,
        )
    assert evidence.deletes == sections.deletes == []


def test_structured_table_wiki_keeps_exact_source_once():
    document = table_document()
    document.chunks = prepare_ingestion_chunks(document)
    document.sections = build_document_sections(document)
    wiki = build_wiki_chunks(document)
    assert len(wiki) == 1
    assert wiki[0].content_type == "table"
    assert wiki[0].content == document.content


def test_registry_retains_all_current_formats_and_list_contract(tmp_path):
    parser = DocumentParser()
    assert {".pdf", ".docx", ".doc", ".pptx", ".html", ".md", ".xlsx"} <= set(parser.supported_extensions)
    source = tmp_path / "notes.md"
    source.write_text("# Notes\n\nA retained source.", encoding="utf-8")
    parsed = parser.parse(str(source))
    assert isinstance(parsed, list) and len(parsed) == 1


def test_cross_page_vector_metadata_never_claims_one_scalar_region():
    document = table_document()
    table = document.content_blocks[0].table
    table.page_regions.append(PageRegion(
        page_number=3, bbox=BoundingBox(x0=5, y0=10, x1=50, y1=70), sources=["table"],
    ))
    table.source_pages = [2, 3]
    columns = provenance_columns(prepare_ingestion_chunks(document))
    assert columns["page_numbers"] == [0, 0]
    assert columns["bbox_jsons"] == ["", ""]
    assert [r["page_number"] for r in json.loads(columns["metadata_jsons"][0])["page_regions"]] == [2, 3]


def test_targeted_ingestion_uses_configured_collections_and_shared_provenance(tmp_path, monkeypatch):
    from pipeline import process_specific_files as targeted

    stores = []
    def store_factory(**kwargs):
        store = FakeStore(kwargs.get("collection_name", "isolated_evidence"))
        stores.append(store)
        return store

    monkeypatch.setattr(targeted, "MilvusStore", store_factory)
    monkeypatch.setenv("SECTION_MILVUS_COLLECTION", "isolated_sections")
    monkeypatch.setenv("WIKI_INGEST_ENABLED", "false")
    monkeypatch.setattr(targeted, "parse_file", lambda path: [table_document()])
    monkeypatch.setattr(auto_process, "embed_texts", lambda texts: [[1.0] for _ in texts])
    monkeypatch.setattr(auto_process, "save_document", lambda *args: None)
    monkeypatch.setattr(targeted.BM25Index, "build_from_documents", lambda *args: None)
    monkeypatch.setattr(targeted.BM25Index, "save", lambda *args: None)
    source = tmp_path / "upload.pdf"
    source.write_bytes(b"disposable parser fixture")
    assert len(targeted.process_specific_files([str(source)])) == 1
    assert [store.collection_name for store in stores] == ["isolated_evidence", "isolated_sections"]
    assert stores[0].rows["table_ids"] == ["sales", "sales"]
