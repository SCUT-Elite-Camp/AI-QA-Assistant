"""Durable upload job state and publication; processing stays shared."""
from pipeline.files.evidence import prepare_persisted_document, persisted_evidence_document
from pipeline.indexing.vectors import index_document_vectors


def ingest_persisted_document(store, vector_store, attachment, job):
    """Consume a durable parse and publish a new private index generation."""
    from uuid import uuid4
    from data_persistence.private_files import publish_file_projection

    preserve_active = bool(job["payload"].get("preserve_active")) and bool(attachment.get("active"))
    parsed = store.load_parsed_document(attachment["id"])
    if parsed is None:
        raise RuntimeError("missing_parsed_document")
    if not preserve_active:
        store.transition_attachment(attachment["id"], "chunking")
    evidence, sections = prepare_persisted_document(parsed, attachment)
    if not evidence:
        raise RuntimeError("empty_parse_result")
    if not sections:
        raise RuntimeError("empty_structure_result")
    if not preserve_active:
        store.transition_attachment(attachment["id"], "embedding")
    if vector_store is None:
        raise RuntimeError("library_vector_index_disabled")
    old_ref, new_ref = publish_file_projection(
        store, attachment, evidence, job["id"], sections,
        write_vectors=lambda ref: index_document_vectors(persisted_evidence_document(ref, evidence), vector_store),
        delete_vectors=vector_store.delete_document_chunks,
    )
    current = store.get_attachment(attachment["id"], include_deleted=True)
    if not current or current["status"] in {"deleted", "expired"}:
        # An upload deleted during embedding must never become READY again.
        vector_store.delete_document_chunks(new_ref)
        raise RuntimeError("parse_cancelled")
    if not preserve_active:
        store.transition_attachment(attachment["id"], "indexing")
    store.update_attachment(attachment["id"], status="ready", error_code="")
    if old_ref and old_ref != new_ref:
        store.enqueue(f"job_{uuid4().hex}", attachment["id"], "cleanup_index", {"vector_ref": old_ref})
