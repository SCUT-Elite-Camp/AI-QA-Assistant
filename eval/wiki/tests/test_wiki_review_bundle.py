from __future__ import annotations

import json
import sqlite3

import pytest

from eval.wiki.export_claim_review import main as export_claims
from eval.wiki.export_review_bundle import main as export_bundle


def _database(path) -> None:
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE wiki_build_runs(source_scope,owner_id,knowledge_base_id,revision,status,input_hash,generator_model,prompt_version,created_at,activated_at);
        CREATE TABLE wiki_candidates(source_scope,owner_id,knowledge_base_id,revision,candidate_id,payload);
        CREATE TABLE wiki_identities(source_scope,owner_id,knowledge_base_id,revision,identity_id,kind,canonical_name,slug,category,description,candidate_ids,source_ids);
        CREATE TABLE wiki_identity_aliases(source_scope,owner_id,knowledge_base_id,revision,identity_id,alias);
        CREATE TABLE wiki_pages(source_scope,owner_id,knowledge_base_id,page_id,page_type,slug,title,identity_id);
        CREATE TABLE wiki_page_revisions(source_scope,owner_id,knowledge_base_id,revision,page_id,page_type,slug,title,identity_id,status,summary,folder_id,document_version_ids,input_hash,generator_model,prompt_version,payload);
        CREATE TABLE wiki_page_claims(source_scope,owner_id,knowledge_base_id,revision,page_id,claim_id,section_heading,claim_text,verdict,reason_code,reason);
        CREATE TABLE wiki_page_sources(source_scope,owner_id,knowledge_base_id,revision,page_id,claim_id,source_id,document_id,document_version_id,section_id,evidence_id,support_quote,quote_start,quote_end,evidence_sha256);
        CREATE TABLE wiki_claim_audits(source_scope,owner_id,knowledge_base_id,revision,page_id,audit_round,claim_id,claim_text,source_ids,verdict,reason_code,reason);
        CREATE TABLE wiki_claim_repairs(source_scope,owner_id,knowledge_base_id,revision,page_id,repair_round,original_claim_id,original_text,action,repaired_claim_id,repaired_text,source_ids,reason);
        """)
        key = ("enterprise", "", "kb", "r1")
        db.execute("INSERT INTO wiki_build_runs VALUES(?,?,?,?,?,?,?,?,?,?)", (*key, "DRAFT", "hash", "fake", "v1", 1, None))
        candidate = {
            "id": "c1", "kind": "CONCEPT", "category": None, "name": "RAG",
            "aliases": [], "description": "retrieval", "status": "EVIDENCE_BOUND",
            "promotion_status": "PROMOTED", "promotion_reason": "reusable",
            "document_ids": ["d1"], "sources": [{"evidence_id": "e1"}],
        }
        db.execute("INSERT INTO wiki_candidates VALUES(?,?,?,?,?,?)", (*key, "c1", json.dumps(candidate)))
        db.execute("INSERT INTO wiki_identities VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (*key, "i1", "CONCEPT", "RAG", "rag", None, "", '[\"c1\"]', '[\"s1\"]'))
        db.execute("INSERT INTO wiki_identity_aliases VALUES(?,?,?,?,?,?)", (*key, "i1", "Retrieval Augmented Generation"))
        page = {"sections": [{"heading": "Overview", "claims": [{"id": "cl1", "text": "RAG uses retrieval.", "source_ids": ["s1"]}]}], "links": []}
        db.execute("INSERT INTO wiki_pages VALUES(?,?,?,?,?,?,?,?)", ("enterprise", "", "kb", "p1", "CONCEPT", "rag", "RAG", "i1"))
        db.execute("INSERT INTO wiki_page_revisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (*key, "p1", "CONCEPT", "rag", "RAG", "i1", "REVIEWING", "summary", None, '[\"v1\"]', "ph", "fake", "v1", json.dumps(page)))
        db.execute("INSERT INTO wiki_page_claims VALUES(?,?,?,?,?,?,?,?,?,?,?)", (*key, "p1", "cl1", "Overview", "RAG uses retrieval.", "SUPPORTED", "ENTAILED", "ok"))
        db.execute("INSERT INTO wiki_page_sources VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (*key, "p1", "cl1", "s1", "d1", "v1", "sec1", "e1", "RAG uses retrieval.", 0, 19, "a" * 64))
        db.execute("INSERT INTO wiki_claim_audits VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (*key, "p1", 1, "cl1", "RAG uses retrieval.", '[\"s1\"]', "SUPPORTED", "ENTAILED", "ok"))


def test_review_exports_are_one_claim_per_row_and_refuse_overwrite(tmp_path) -> None:
    database = tmp_path / "wiki.sqlite3"
    _database(database)
    claims = tmp_path / "claims.csv"
    assert export_claims([str(database), "--revision", "r1", "--output", str(claims)]) == 0
    assert len(claims.read_text(encoding="utf-8-sig").splitlines()) == 2
    with pytest.raises(FileExistsError):
        export_claims([str(database), "--revision", "r1", "--output", str(claims)])

    output = tmp_path / "bundle"
    assert export_bundle([str(database), "--revision", "r1", "--output-dir", str(output)]) == 0
    stats = json.loads((output / "stats.json").read_text(encoding="utf-8"))
    assert stats["final_claims"] == 1 and stats["human_review"] == "NOT_RUN"
    assert output.with_suffix(".zip").exists()
    with pytest.raises(FileExistsError):
        export_bundle([str(database), "--revision", "r1", "--output-dir", str(output)])
