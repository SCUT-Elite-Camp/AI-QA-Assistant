from __future__ import annotations

import hashlib

import pytest

from storage.wiki_review_release import create_reviewed_revision
from storage.wiki_store import WikiStore


def _draft(store: WikiStore) -> None:
    scope = {"source_scope": "enterprise", "owner_id": "", "knowledge_base_id": "kb"}
    quote = "A meeting states the project is planned."
    source = {
        "document_id": "doc", "document_version_id": "v1", "section_id": "section",
        "evidence_id": "ev1", "support_quote": quote, "quote_start": 0,
        "quote_end": len(quote), "evidence_sha256": hashlib.sha256(quote.encode()).hexdigest(),
    }
    pages = []
    audits = []
    for page_id in ("good", "rejected"):
        claim = {"id": f"claim-{page_id}", "text": f"Claim on {page_id}.",
                 "rendered_text": f"Claim on {page_id}.", "source_ids": ["s1"],
                 "verdict": "SUPPORTED", "reason_code": "ENTAILED", "reason": "checked"}
        pages.append({
            "id": page_id, "scope": scope, "page_type": "SUMMARY", "slug": page_id,
            "title": page_id, "summary": "See [rejected](/wiki/rejected)",
            "identity_id": None, "document_version_ids": ["v1"],
            "sections": [{"heading": "Notes", "claims": [claim]}],
            "links": ["rejected"] if page_id == "good" else [],
            "status": "REVIEWING", "input_hash": page_id,
        })
        audits.append({
            "page_id": page_id, "audit_round": 1, "claim_id": claim["id"],
            "claim_text": claim["text"], "source_ids": ["s1"],
            "verdict": "SUPPORTED", "reason_code": "ENTAILED", "reason": "checked",
        })
    pages.append({
        "id": "index", "scope": scope, "page_type": "INDEX", "slug": "index",
        "title": "Index", "summary": "Index", "identity_id": None,
        "document_version_ids": [], "sections": [], "links": ["good", "rejected"],
        "status": "REVIEWING", "input_hash": "index",
    })
    store.save_artifact({
        "scope": scope, "revision": "draft", "input_hash": "build-source",
        "generator_model": "model", "prompt_version": "v1",
        "documents": [{"document_id": "doc", "document_version_id": "v1",
                       "content_sha256": source["evidence_sha256"]}],
        "candidates": [], "identities": [], "folders": [], "pages": pages,
        "claim_audits": audits, "claim_repairs": [], "issues": [],
    }, {"s1": source})


def test_reviewed_release_excludes_rejected_page_and_preserves_claim_evidence(tmp_path):
    store = WikiStore(tmp_path / "wiki.sqlite3")
    _draft(store)
    context = {"source_scope": "enterprise", "owner_id": "", "knowledge_base_id": "kb"}
    revision = create_reviewed_revision(
        store, **context, source_revision="draft", review_sha256="a" * 64,
        page_ids={"good", "index"}, identity_ids=set(), candidate_ids=set(),
        reviewer="reviewer", reviewed_on="2026-09-17",
    )
    store.publish_revision(**context, revision=revision)
    with store.connection() as db:
        original = db.execute("SELECT status FROM wiki_build_runs WHERE revision='draft'").fetchone()
        assert original["status"] == "DRAFT"
        assert db.execute("SELECT COUNT(*) FROM wiki_page_revisions WHERE revision='draft'").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM wiki_page_revisions WHERE revision=?", (revision,)).fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM wiki_page_claims WHERE revision=?", (revision,)).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM wiki_page_links WHERE revision=? AND target_page_id='rejected'",
                          (revision,)).fetchone()[0] == 0
        metadata = db.execute("SELECT reviewer,review_sha256 FROM wiki_reviewed_releases WHERE revision=?",
                              (revision,)).fetchone()
        assert tuple(metadata) == ("reviewer", "a" * 64)
    page = store.read_page("good", **context)
    assert page["summary"] == "See rejected"
    assert page["sections"][0]["claims"][0]["text"] == "Claim on good."
    assert store.read_sources("good", **context)[0]["evidence_id"] == "ev1"
    assert store.read_page("rejected", **context) is None
    assert store.load_published_candidates("v1", **context) is None
    assert store.reusable_revision(input_hash="build-source", **context) is None


def test_reviewed_release_requires_draft_and_rolls_back_on_invalid_selection(tmp_path):
    store = WikiStore(tmp_path / "wiki.sqlite3")
    _draft(store)
    context = {"source_scope": "enterprise", "owner_id": "", "knowledge_base_id": "kb"}
    with pytest.raises(ValueError, match="unknown page"):
        create_reviewed_revision(
            store, **context, source_revision="draft", review_sha256="a" * 64,
            page_ids={"missing"}, identity_ids=set(), candidate_ids=set(),
            reviewer="reviewer", reviewed_on="2026-09-17",
        )
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM wiki_reviewed_releases").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM wiki_build_runs").fetchone()[0] == 1
