from __future__ import annotations

import json
import sqlite3

from eval.wiki.run_phase8_integration import _retain_reviewed_pages
from storage.wiki_store import WikiStore


def test_isolated_reviewed_subset_excludes_failed_pages_and_dead_links(tmp_path):
    original = tmp_path / "source.sqlite3"
    WikiStore(original)
    context = ("enterprise", "", "kb", "revision")
    with sqlite3.connect(original) as db:
        for page_id, slug, status in (
            ("passed", "passed", "REVIEWING"),
            ("failed", "failed", "FAILED"),
        ):
            payload = {
                "links": ["failed"] if page_id == "passed" else [],
                "summary": "Read [failed](/wiki/failed) for context",
                "sections": [{"heading": "A", "claims": [{
                    "id": "claim", "text": "Some claim", "rendered_text": "See [failed](/wiki/failed)",
                    "source_ids": ["source"],
                }]}],
            }
            db.execute(
                "INSERT INTO wiki_page_revisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (*context, page_id, "SUMMARY", slug, page_id, None, status,
                 payload["summary"], None, "[]", "hash", "model", "v1",
                 json.dumps(payload)),
            )
        db.execute("INSERT INTO wiki_page_links VALUES(?,?,?,?,?,?)", (*context, "passed", "failed"))
    clone = tmp_path / "clone.sqlite3"
    with sqlite3.connect(original) as source, sqlite3.connect(clone) as target:
        source.backup(target)

    assert _retain_reviewed_pages(clone, "revision", "kb") == 1
    with sqlite3.connect(clone) as db:
        rows = db.execute(
            "SELECT page_id,summary,payload FROM wiki_page_revisions WHERE revision='revision'",
        ).fetchall()
        assert len(rows) == 1 and rows[0][0] == "passed"
        assert db.execute("SELECT COUNT(*) FROM wiki_page_links").fetchone()[0] == 0
        payload = json.loads(rows[0][2])
        assert payload["links"] == []
        assert payload["summary"] == "Read failed for context"
        assert payload["sections"][0]["claims"][0]["rendered_text"] == "See failed"
    with sqlite3.connect(original) as db:
        assert db.execute("SELECT COUNT(*) FROM wiki_page_revisions").fetchone()[0] == 2
