from __future__ import annotations

import json
import sqlite3

import pytest

from eval.wiki.export_review_bundle import main as export_review_bundle
from eval.wiki.publish_reviewed_subset import (
    _verify_database_matches_bundle, select_reviewed_pages,
)
from storage.wiki_store import WikiStore


def test_selection_excludes_any_page_with_rejected_review_chain():
    tables = {
        "01-candidates": [
            {"candidate_id": "ok", "promotion_status": "PROMOTED",
             "human_candidate_valid": "TRUE", "human_type_valid": "TRUE",
             "human_promotion_valid": "TRUE"},
            {"candidate_id": "bad", "promotion_status": "PROMOTED",
             "human_candidate_valid": "TRUE", "human_type_valid": "FALSE",
             "human_promotion_valid": "FALSE"},
        ],
        "02-identities": [
            {"identity_id": "i-ok", "candidate_ids_json": '["ok"]',
             "human_identity_valid": "TRUE", "human_merge_valid": "TRUE"},
            {"identity_id": "i-bad", "candidate_ids_json": '["bad"]',
             "human_identity_valid": "TRUE", "human_merge_valid": "TRUE"},
        ],
        "03-pages": [
            {"page_id": name, "identity_id": identity, "page_type": "CONCEPT",
             "status": "REVIEWING", "human_page_worthy": "TRUE",
             "human_summary_supported": "TRUE"}
            for name, identity in (("good", "i-ok"), ("bad-identity", "i-bad"),
                                   ("bad-claim", "i-ok"), ("bad-audit", "i-ok"),
                                   ("bad-summary", "i-ok"))
        ],
        "04-final-claims": [
            {"page_id": name, "human_supported": "FALSE" if name == "bad-claim" else "TRUE"}
            for name in ("good", "bad-identity", "bad-claim", "bad-audit", "bad-summary")
        ],
        "05-audit-events": [{"page_id": "bad-audit", "human_event_valid": "FALSE"}],
        "06-repair-events": [],
    }
    tables["03-pages"][-1]["human_summary_supported"] = "FALSE"
    selected = select_reviewed_pages(tables)
    assert selected == {"pages": {"good"}, "identities": {"i-ok"}, "candidates": {"ok"}}


def test_selection_fails_closed_when_only_index_remains():
    tables = {
        "01-candidates": [], "02-identities": [],
        "03-pages": [{"page_id": "index", "identity_id": "", "page_type": "INDEX",
                      "status": "REVIEWING", "human_page_worthy": "TRUE",
                      "human_summary_supported": "TRUE"}],
        "04-final-claims": [], "05-audit-events": [], "06-repair-events": [],
    }
    with pytest.raises(ValueError, match="no content page"):
        select_reviewed_pages(tables)


def test_release_refuses_database_changed_after_human_review(tmp_path):
    database = tmp_path / "wiki.sqlite3"
    WikiStore(database)
    context = ("enterprise", "", "kb", "draft")
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO wiki_build_runs VALUES(?,?,?,?,?,?,?,?,?,NULL)",
                   (*context, "DRAFT", "input", "model", "v1", 1))
        page = {"id": "p1", "sections": [], "links": [], "summary": "reviewed summary"}
        db.execute("INSERT INTO wiki_page_revisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (*context, "p1", "INDEX", "index", "Index", None, "REVIEWING",
                    "reviewed summary", None, "[]", "hash", "model", "v1", json.dumps(page)))
    bundle = tmp_path / "bundle"
    export_review_bundle([str(database), "--revision", "draft", "--output-dir", str(bundle)])
    with sqlite3.connect(database) as db:
        db.execute("UPDATE wiki_page_revisions SET summary='changed' WHERE revision='draft'")
    with pytest.raises(ValueError, match="source Wiki revision differs"):
        _verify_database_matches_bundle(database, "draft", bundle)
