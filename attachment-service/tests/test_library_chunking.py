from attachment_service.chunking import chunk_attachment_evidence
from attachment_service.store import AttachmentStore


def _raw(content: str, *, source_type: str = "document_text", locator=None):
    return [{
        "evidence_id": "random-parser-id",
        "attachment_id": "ver_a",
        "source_type": source_type,
        "content": content,
        "locator": locator or {},
        "confidence": 1.0,
        "parser": "test",
    }]


def test_long_markdown_is_chunked_with_stable_ids_and_section_locators():
    text = "# Intro\n" + ("overview " * 80) + "\n## Retrieval\n" + ("tail-token " * 180)

    chunks = chunk_attachment_evidence(_raw(text), "ver_a", ".md", chunk_size=300, overlap=40)

    assert len(chunks) > 2
    assert [item["evidence_id"] for item in chunks] == [
        f"ver_a_chunk_{index}" for index in range(len(chunks))
    ]
    retrieval = [item for item in chunks if "tail-token" in item["content"]]
    assert retrieval
    assert retrieval[0]["locator"]["section_path"] == ["Intro", "Retrieval"]
    assert retrieval[0]["locator"]["char_end"] > retrieval[0]["locator"]["char_start"]


def test_long_text_is_chunked_and_keeps_original_locator():
    chunks = chunk_attachment_evidence(
        _raw("alpha " * 500, locator={"page": 4}),
        "ver_text",
        ".txt",
        chunk_size=240,
        overlap=40,
    )
    assert len(chunks) > 1
    assert all(item["locator"]["page"] == 4 for item in chunks)
    assert max(len(item["content"]) for item in chunks) <= 240


def test_large_table_remains_one_semantic_chunk():
    table = "\n".join(f"row {index} | value" for index in range(300))
    chunks = chunk_attachment_evidence(
        _raw(table, source_type="table", locator={"sheet": "Revenue", "cell_range": "A1:F300"}),
        "ver_table",
        ".xlsx",
        chunk_size=200,
    )
    assert len(chunks) == 1
    assert chunks[0]["locator"]["sheet"] == "Revenue"
    assert chunks[0]["locator"]["cell_range"] == "A1:F300"


def test_long_markdown_tail_section_is_retrievable(tmp_path):
    text = "# Intro\n" + ("overview " * 120) + "\n## Deployment\n" + ("sentinel-tail-token " * 120)
    chunks = chunk_attachment_evidence(_raw(text), "ver_a", ".md", chunk_size=300, overlap=40)
    store = AttachmentStore(tmp_path / "library.sqlite3")
    store.create_attachment({
        "id": "ver_a",
        "filename": "long.md",
        "mime_type": "text/markdown",
        "extension": ".md",
        "size_bytes": len(text),
        "sha256": "a" * 64,
        "owner_id": "user-a",
        "dedupe_domain": "user:user-a",
        "scope": "library",
        "status": "ready",
        "blob_path": str(tmp_path / "long.md"),
        "key_id": "test",
        "created_at": 1,
        "updated_at": 1,
        "knowledge_base_id": "kb-a",
        "document_id": "doc-a",
        "version_id": "ver_a",
        "source_scope": "personal",
        "active": 1,
        "version_number": 1,
    })
    store.replace_evidence("ver_a", chunks)

    matches = store.search_evidence(["ver_a"], "sentinel tail token", top_k=3)

    assert matches
    assert matches[0]["locator"]["section_path"] == ["Intro", "Deployment"]
