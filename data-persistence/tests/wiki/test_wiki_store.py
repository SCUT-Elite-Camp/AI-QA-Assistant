from __future__ import annotations

import hashlib

import pytest

from storage.wiki_store import WikiStore


def _source():
    text = "Retrieval-Augmented Generation uses retrieval."
    return {
        "document_id": "doc-1", "document_version_id": "ver-1",
        "evidence_id": "ev-1", "section_id": "sec-1", "support_quote": text,
        "quote_start": 0, "quote_end": len(text),
        "evidence_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def _source_id(source):
    raw = "\n".join([source["document_version_id"], source["evidence_id"], "0", str(source["quote_end"])])
    return "ws_" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def _artifact(revision="r1", *, page_status="REVIEWING", verdict="SUPPORTED", reason="ENTAILED"):
    scope = {"source_scope": "enterprise", "owner_id": "", "knowledge_base_id": "kb"}
    source = _source()
    source_id = _source_id(source)
    candidate = {
        "id": "candidate-1", "scope": scope, "kind": "CONCEPT", "name": "RAG",
        "category": None, "aliases": ["Retrieval-Augmented Generation"], "description": "",
        "document_ids": ["doc-1"], "sources": [source], "status": "EVIDENCE_BOUND",
        "generator_model": "fake", "prompt_version": "v1", "input_hash": "candidate-hash",
    }
    identity = {
        "id": "identity-1", "scope": scope, "kind": "CONCEPT", "canonical_name": "RAG",
        "slug": "rag-identity", "category": None, "aliases": ["Retrieval-Augmented Generation"],
        "candidate_ids": ["candidate-1"], "source_ids": [source_id], "description": "",
    }
    folder = {"id": "folder-1", "scope": scope, "title": "Methods", "parent_id": None, "depth": 0, "manual": False}
    page = {
        "id": "page-1", "scope": scope, "page_type": "CONCEPT", "slug": "rag-identity",
        "title": "RAG", "summary": "Retrieval method", "folder_id": "folder-1",
        "identity_id": "identity-1", "document_version_ids": ["ver-1"],
        "sections": [{"heading": "Overview", "claims": [{
            "id": "claim-1", "text": "RAG uses retrieval.", "source_ids": [source_id],
            "verdict": verdict, "reason_code": reason, "reason": "checked",
        }]}],
        "links": ["page-index"], "status": page_status, "generator_model": "fake",
        "prompt_version": "v1", "input_hash": "page-hash",
    }
    index = {
        "id": "page-index", "scope": scope, "page_type": "INDEX", "slug": "index",
        "title": "Knowledge Index", "summary": "Index", "folder_id": None,
        "identity_id": None, "document_version_ids": [], "sections": [],
        "links": ["page-1"], "status": page_status, "generator_model": "deterministic",
        "prompt_version": "v1", "input_hash": f"index-{revision}",
    }
    artifact = {
        "scope": scope, "revision": revision, "input_hash": f"build-{revision}",
        "generator_model": "fake", "prompt_version": "v1",
        "documents": [{"document_id": "doc-1", "document_version_id": "ver-1",
                       "content_sha256": source["evidence_sha256"]}],
        "candidates": [candidate],
        "identities": [identity], "folders": [folder], "pages": [page, index],
        "claim_audits": [{
            "page_id": "page-1", "audit_round": 1, "claim_id": "claim-1",
            "claim_text": "RAG uses retrieval.", "source_ids": [source_id],
            "verdict": verdict, "reason_code": reason, "reason": "checked",
        }],
        "claim_repairs": [{
            "page_id": "page-1", "repair_round": 1,
            "original_claim_id": "claim-original",
            "original_text": "RAG always completes retrieval.", "action": "REWRITE",
            "repaired_claim_id": "claim-1", "repaired_text": "RAG uses retrieval.",
            "source_ids": [source_id], "reason": "remove unsupported completion",
        }], "issues": [],
    }
    return artifact, {source_id: source}


def test_store_atomically_publishes_searches_and_reads_sources(tmp_path) -> None:
    store = WikiStore(tmp_path / "wiki.sqlite3")
    artifact, sources = _artifact()
    store.save_artifact(artifact, sources)
    assert store.search_pages("RAG", source_scope="enterprise", owner_id="", knowledge_base_id="kb") == []

    store.publish_revision(source_scope="enterprise", owner_id="", knowledge_base_id="kb", revision="r1")
    rows = store.search_pages("Retrieval", source_scope="enterprise", owner_id="", knowledge_base_id="kb")
    assert rows[0]["page_id"] == "page-1"
    assert rows[0]["citation_authority"] is False
    page = store.read_page("rag-identity", source_scope="enterprise", owner_id="", knowledge_base_id="kb")
    assert page and page["status"] == "PUBLISHED"
    refs = store.read_sources("page-1", source_scope="enterprise", owner_id="", knowledge_base_id="kb")
    assert refs[0]["evidence_id"] == "ev-1"
    assert store.reusable_revision(
        source_scope="enterprise", owner_id="", knowledge_base_id="kb", input_hash="build-r1",
    ) == "r1"
    assert len(store.load_published_candidates(
        "ver-1", source_scope="enterprise", owner_id="", knowledge_base_id="kb",
    )) == 1
    assert store.load_published_candidates(
        "ver-missing", source_scope="enterprise", owner_id="", knowledge_base_id="kb",
    ) is None
    history = store.load_published_page_audit_cache(
        source_scope="enterprise", owner_id="", knowledge_base_id="kb",
    )["page-hash"]
    assert history["audits"][0]["claim_id"] == "claim-1"
    assert history["repairs"][0]["original_claim_id"] == "claim-original"


def test_failed_revision_cannot_replace_previous_published_revision(tmp_path) -> None:
    store = WikiStore(tmp_path / "wiki.sqlite3")
    first, sources = _artifact()
    store.save_artifact(first, sources)
    store.publish_revision(source_scope="enterprise", owner_id="", knowledge_base_id="kb", revision="r1")
    failed, sources = _artifact("r2", page_status="FAILED", verdict="INSUFFICIENT", reason="OVERSTATED")
    failed["pages"][0]["title"] = "Unpublished RAG title"
    failed["pages"][0]["slug"] = "unpublished-rag-title"
    store.save_artifact(failed, sources)
    with pytest.raises(ValueError, match="pass review"):
        store.publish_revision(source_scope="enterprise", owner_id="", knowledge_base_id="kb", revision="r2")
    assert store.read_page(
        "page-1", source_scope="enterprise", owner_id="", knowledge_base_id="kb",
    )["status"] == "PUBLISHED"
    live = store.search_pages(
        "Retrieval", source_scope="enterprise", owner_id="", knowledge_base_id="kb",
    )
    assert live[0]["title"] == "RAG" and live[0]["slug"] == "rag-identity"


def test_publish_rejects_supported_claim_without_audit_history(tmp_path) -> None:
    store = WikiStore(tmp_path / "wiki.sqlite3")
    artifact, sources = _artifact()
    artifact["claim_audits"] = []
    store.save_artifact(artifact, sources)
    with pytest.raises(ValueError, match="audit record"):
        store.publish_revision(
            source_scope="enterprise", owner_id="", knowledge_base_id="kb", revision="r1",
        )


@pytest.mark.parametrize("tamper", ["text", "sources"])
def test_publish_rejects_claim_changed_after_audit(tmp_path, tamper) -> None:
    store = WikiStore(tmp_path / "wiki.sqlite3")
    artifact, sources = _artifact()
    if tamper == "text":
        artifact["pages"][0]["sections"][0]["claims"][0]["text"] = "RAG always uses retrieval."
    else:
        artifact["claim_audits"][0]["source_ids"] = ["different-source"]
    store.save_artifact(artifact, sources)
    with pytest.raises(ValueError, match="exact supported audit"):
        store.publish_revision(
            source_scope="enterprise", owner_id="", knowledge_base_id="kb", revision="r1",
        )


def test_deleted_source_hides_published_revision_and_blocks_stale_writes(tmp_path) -> None:
    store = WikiStore(tmp_path / "wiki.sqlite3")
    context = {"source_scope": "enterprise", "owner_id": "", "knowledge_base_id": "kb"}
    artifact, sources = _artifact()
    store.save_artifact(artifact, sources)
    store.publish_revision(**context, revision="r1")
    assert store.search_pages("RAG", **context)

    store.upsert_pending_wiki_op(
        **context, document_id="doc-1", document_version_id="ver-1",
        content_sha256="0" * 64, operation="DELETE",
    )
    assert store.schedule_pending_wiki_jobs()
    assert store.search_pages("RAG", **context) == []
    assert store.read_page("page-1", **context) is None
    assert store.read_sources("page-1", **context) == []
    assert store.active_vector_pages(**context) == ("", [])
    with pytest.raises(ValueError, match="deleted during build"):
        store.save_artifact({**artifact, "revision": "r2"}, sources)
    with store.connection() as db:
        db.execute("UPDATE wiki_build_runs SET status='DRAFT' WHERE revision='r1'")
    with pytest.raises(ValueError, match="deleted during build"):
        store.publish_revision(**context, revision="r1")

    store.reactivate_wiki_source(**context, document_id="doc-1")
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM wiki_source_tombstones").fetchone()[0] == 0


def test_personal_scope_never_leaks_to_another_owner(tmp_path) -> None:
    store = WikiStore(tmp_path / "wiki.sqlite3")
    with pytest.raises(ValueError, match="owner"):
        store.search_pages("RAG", source_scope="personal", owner_id="", knowledge_base_id="kb")


def test_completion_cache_is_exact_and_does_not_mutate_existing_response(tmp_path) -> None:
    store = WikiStore(tmp_path / "wiki.sqlite3")
    response = {"candidates": [{"name": "RAG"}]}
    store.put_completion(
        "a" * 64, model="deepseek-v4-pro", schema_name="candidate", response=response,
    )
    response["candidates"][0]["name"] = "changed outside store"

    assert store.get_completion("a" * 64) == {"candidates": [{"name": "RAG"}]}
    assert store.get_completion("b" * 64) is None
    with pytest.raises(ValueError, match="SHA-256"):
        store.get_completion("short")
