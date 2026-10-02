import json

from models.document import Document


def test_document_infers_type_from_file_extension(tmp_path):
    path = tmp_path / "policy.PDF"
    path.write_text("policy", encoding="utf-8")

    document = Document.from_file_path(str(path), "policy")

    assert document.doc_type == "pdf"


def test_document_prefers_specific_sidecar_type(tmp_path):
    path = tmp_path / "export.bin"
    path.write_text("policy", encoding="utf-8")
    (tmp_path / "export.bin.meta.json").write_text(
        json.dumps({"content_type": "application/pdf"}),
        encoding="utf-8",
    )

    document = Document.from_file_path(str(path), "policy")

    assert document.doc_type == "pdf"


def test_document_uses_attachment_filename_extension():
    assert Document.infer_doc_type(
        "confluence:123",
        {"content_type": "attachment", "filename": "policy.DOCX"},
    ) == "docx"
