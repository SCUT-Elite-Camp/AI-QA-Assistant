from __future__ import annotations

import csv
import hashlib
import json

import pytest

from eval.wiki.verify_gate_c_claim_submission import validate


def _csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_review_submission_preserves_frozen_evidence_and_scores_claims(tmp_path):
    sample_dir = tmp_path / "sample"
    bundle = tmp_path / "bundle"
    sample_dir.mkdir()
    bundle.mkdir()
    source = bundle / "04-final-claims.csv"
    source.write_text("frozen claims", encoding="utf-8")
    rows = [
        {"claim_id": "c1", "claim_text": "fact", "source_quotes_json": '["evidence"]',
         "human_supported": "", "human_issue_type": "", "human_notes": ""},
        {"claim_id": "c2", "claim_text": "plan as fact", "source_quotes_json": '["plan"]',
         "human_supported": "", "human_issue_type": "", "human_notes": ""},
    ]
    _csv(sample_dir / "claim-review-100.csv", rows)
    (sample_dir / "manifest.json").write_text(json.dumps({
        "revision": "r1", "source_claims_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "selected_claim_ids": ["c1", "c2"],
    }), encoding="utf-8")
    reviewed = [dict(row) for row in rows]
    reviewed[0].update(human_supported="TRUE", human_notes="supported by quote")
    reviewed[1].update(human_supported="FALSE", human_issue_type="PLAN_AS_FACT",
                       human_notes="source states only a plan")
    submission = tmp_path / "reviewed.csv"
    _csv(submission, reviewed)

    result = validate(sample_dir, submission, bundle)
    assert result["submitted_supported"] == 1
    assert result["submitted_unsupported"] == 1
    assert result["gate_c"] == "NOT_RUN"
    assert result["unsupported_claims"][0]["claim_id"] == "c2"

    reviewed[0]["source_quotes_json"] = '["changed evidence"]'
    _csv(submission, reviewed)
    with pytest.raises(ValueError, match="Evidence changed"):
        validate(sample_dir, submission, bundle)
