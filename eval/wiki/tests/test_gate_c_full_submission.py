from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile

import pytest

from eval.wiki.verify_gate_c_full_submission import TABLES, VERDICT_COLUMNS, validate


def _csv_bytes(rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def _fixture(tmp_path, *, changed_source=False):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    originals = {
        "01-candidates": {"candidate_id": "c1", "promotion_status": "PROMOTED"},
        "02-identities": {"identity_id": "i1"},
        "03-pages": {"page_id": "p1", "status": "REVIEWING"},
        "04-final-claims": {"page_id": "p1", "claim_id": "cl1", "claim_text": "a claim"},
        "05-audit-events": {"claim_id": "cl1"},
        "06-repair-events": {"original_claim_id": "cl1"},
    }
    manifest = {"revision": "r1", "files": {}}
    reviewed = {}
    for name in TABLES:
        content = _csv_bytes([originals[name]])
        (bundle / f"{name}.csv").write_bytes(content)
        manifest["files"][f"{name}.csv"] = hashlib.sha256(content).hexdigest()
        reviewed[name] = {**originals[name], **{field: "TRUE" for field in VERDICT_COLUMNS[name]},
                          "human_notes": "checked against source"}
    if changed_source:
        reviewed["04-final-claims"]["claim_text"] = "altered claim"
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (bundle / "stats.json").write_text(json.dumps({
        "revision": "r1", "final_claims": 1, "candidates": 1,
    }), encoding="utf-8")
    summary = []
    for name in TABLES:
        for field in VERDICT_COLUMNS[name]:
            summary.append({"file": f"{name}-human-reviewed.csv", "human_field": field,
                            "TRUE": 1, "FALSE": 0, "other_or_blank": 0})
    summary.append({"file": "04-final-claims-human-reviewed.csv", "human_field": "human_issue_type",
                    "TRUE": 0, "FALSE": 0, "other_or_blank": 1})
    reviewed["04-final-claims"]["human_issue_type"] = ""
    archive = tmp_path / "review.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        for name in TABLES:
            zipped.writestr(f"{name}-human-reviewed.csv", _csv_bytes([reviewed[name]]))
        zipped.writestr("review-summary.csv", _csv_bytes(summary))
    return bundle, archive


def test_full_submission_checks_frozen_rows_and_counts(tmp_path):
    bundle, archive = _fixture(tmp_path)
    result = validate(bundle, archive)
    assert result["candidate_precision_90"] == "PASS"
    assert result["claim_support_precision_95"] == "PASS"
    assert result["identity_bad_merges_zero"] == "PASS"
    assert result["semantic_duplicate_page_rate"] == "NOT_RUN"
    assert result["gate_c"] == "PARTIAL"


def test_full_submission_rejects_changed_claim(tmp_path):
    bundle, archive = _fixture(tmp_path, changed_source=True)
    with pytest.raises(ValueError, match="source row changed"):
        validate(bundle, archive)
