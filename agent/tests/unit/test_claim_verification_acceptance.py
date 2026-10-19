"""Safety and metric contracts for offline MiniCheck validation."""
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest

from eval.claim_verification_acceptance import check_acl_denial, load_cases, prepare_reviewed_case, summarize, verify_sources

pytestmark = pytest.mark.no_storage


def test_false_accepts_are_not_hidden_by_supported_accuracy():
    rows = [
        {"case_id":"correct", "expected_verdict":"supported", "verdict":"supported"},
        {"case_id":"invented-year", "expected_verdict":"insufficient_evidence", "verdict":"supported"},
        {"case_id":"reversed-status", "expected_verdict":"contradicted", "verdict":"not_supported"},
    ]
    report = summarize(rows)
    assert report["false_accepts"] == 1 and report["unsupported_cases"] == 2
    assert report["false_accept_ids"] == ["invented-year"]
    assert report["false_accept_rate"] == 0.5 and report["false_rejects"] == 0


def test_unverified_results_are_not_counted_as_supported():
    report = summarize([{"case_id":"timeout", "expected_verdict":"supported", "verdict":"needs_review"}])
    assert report["needs_review"] == 1 and report["verified"] == 0
    assert report["false_rejects"] == 1
    assert report["false_accept_rate"] is None


def test_holdout_cannot_reuse_development_document(tmp_path):
    cases = [{"case_id":str(i), "split":split, "expected_verdict":"supported", "review_reason":"Checked original",
              "evidence":[{"doc_id":"same-source"}]} for i, split in enumerate(["dev", "holdout"])]
    path = tmp_path/"cases.json"
    raw = json.dumps({"reviewer":"Codex", "frozen_before_inference":True, "cases":cases}).encode()
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="holdout_documents_overlap"):
        load_cases(path, hashlib.sha256(raw).hexdigest())


def test_changed_frozen_labels_are_rejected(tmp_path):
    path = tmp_path/"cases.json"
    path.write_text('{"cases":[]}', encoding="utf-8")
    with pytest.raises(ValueError, match="frozen_dataset_changed"):
        load_cases(path, "0"*64)


@pytest.mark.parametrize("language", ["zh", None])
def test_non_english_or_undeclared_cases_require_explicit_opt_in(tmp_path, language):
    case = {"case_id":"language-probe", "split":"regression", "expected_verdict":"supported",
            "review_reason":"Explicit language capability fixture.", "evidence":[{"doc_id":"doc"}],
            "claim_language":language, "source_language":"en"}
    path = tmp_path/"cases.json"
    raw = json.dumps({"reviewer":"Codex", "frozen_before_inference":True, "cases":[case]}).encode()
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match="english_cases_required"):
        load_cases(path, digest)
    assert load_cases(path, digest, allow_non_english=True)["cases"] == [case]


@pytest.mark.parametrize("denial_raises", [False, True])
def test_mutating_negative_uses_copy_and_restores_on_failure(tmp_path, monkeypatch, denial_raises):
    from agent.service.permission_service import PermissionService
    source = tmp_path/"source.sqlite"
    with sqlite3.connect(source) as db:
        db.executescript("""CREATE TABLE users (id TEXT PRIMARY KEY,email TEXT,name TEXT,avatar TEXT,
            username TEXT,provider TEXT,provider_id TEXT,created_at INTEGER,role TEXT,disabled INTEGER);
            INSERT INTO users VALUES ('actor','','','','','','',0,'admin',0);
            CREATE TABLE files (id TEXT PRIMARY KEY,user_id TEXT,visibility TEXT,doc_id TEXT);
            INSERT INTO files VALUES ('file','actor','shared','doc');
            CREATE TABLE file_permissions(file_id TEXT,grant_type TEXT,grant_id TEXT);
            CREATE TABLE user_departments(user_id TEXT,department_id TEXT);""")
        baseline = "\n".join(db.iterdump())
    provider = SimpleNamespace(_load=lambda doc_id: {"doc_id":doc_id}, filter_allowed=lambda actor, ids: ids)
    permissions = SimpleNamespace(db_path=str(source), source_provider=provider,
        get_accessible_doc_ids_strict=lambda *args, **kwargs: ["doc"])
    output = tmp_path/"output"
    output.mkdir()
    if denial_raises:
        def fail(*args, **kwargs):
            raise RuntimeError("native boundary failed")
        monkeypatch.setattr(PermissionService, "get_accessible_doc_ids_strict", fail)
        with pytest.raises(RuntimeError, match="native boundary failed"):
            check_acl_denial(permissions, "actor", "doc", output)
    else:
        assert check_acl_denial(permissions, "actor", "doc", output)["local_acl_denied"]
    with sqlite3.connect(source) as db:
        assert "\n".join(db.iterdump()) == baseline
    with sqlite3.connect(output/"acl-denied.sqlite") as db:
        assert db.execute("SELECT role FROM users WHERE id='actor'").fetchone() == ("admin",)
        assert db.execute("SELECT user_id,visibility FROM files WHERE id='file'").fetchone() == ("actor", "shared")
        assert db.execute("SELECT COUNT(*) FROM users").fetchone() == (1,)


@pytest.mark.parametrize("change,error", [("denied","current_source_access_denied"),
    ("body","frozen_source_changed"), ("quote","original_excerpt_changed")])
def test_current_authority_hash_and_original_fragment_must_match(tmp_path, change, error):
    path = tmp_path/"doc.json"
    raw = json.dumps({"doc_id":"doc", "content":"Source passage"}).encode()
    path.write_bytes(raw)
    evidence = {"doc_id":"doc", "document_file_sha256":hashlib.sha256(raw).hexdigest(),
                "quote":"Source passage", "source_start":0, "source_end":14}
    if change == "body":
        path.write_text(json.dumps({"doc_id":"doc", "content":"Changed passage"}))
    if change == "quote":
        evidence["quote"] = "Fabricated passage"
    permissions = SimpleNamespace(get_accessible_doc_ids_strict=lambda *args, **kwargs: [] if change == "denied" else ["doc"])
    with pytest.raises(ValueError, match=error):
        verify_sources([{"evidence":[evidence]}], tmp_path, permissions, "actor")


@pytest.mark.parametrize("missing_version", [False, True])
def test_reviewed_context_adapter_preserves_later_anchor_and_does_not_invent_lineage(tmp_path, missing_version):
    body = "# Older scope\n\nApproved.\n\n# Current scope\n\nApproved."
    document = {"doc_id":"policy", "content":body, "metadata":{} if missing_version else {"version":7}}
    raw = json.dumps(document).encode()
    (tmp_path/"policy.json").write_bytes(raw)
    case = {"case_id":"reviewed-case", "claim":"The current scope is approved.", "evidence":[{
        "doc_id":"policy", "document_file_sha256":hashlib.sha256(raw).hexdigest(),
        "quote":"Approved.", "source_start":body.rindex("Approved."), "source_end":len(body),
    }]}
    prepared = prepare_reviewed_case(case, tmp_path)
    if missing_version:
        assert prepared.reason == "source_lineage_missing" and not prepared.premise
    else:
        assert prepared.status == "ready" and "# Current scope" in prepared.premise
        assert "# Older scope" not in prepared.premise
        assert prepared.sources[0].anchors[0].start == body.rindex("Approved.")
        assert prepared.sources[0].provenance["source_version"] == "7"


def test_reviewed_context_adapter_rejects_changed_frozen_body_before_constructing_context(tmp_path):
    (tmp_path/"policy.json").write_text(json.dumps({"doc_id":"policy", "content":"Changed policy."}))
    with pytest.raises(ValueError, match="frozen_source_changed"):
        prepare_reviewed_case({"case_id":"changed", "claim":"A claim.", "evidence":[{
            "doc_id":"policy", "document_file_sha256":"0"*64,
            "quote":"policy", "source_start":0,"source_end":6,
        }]}, tmp_path)
