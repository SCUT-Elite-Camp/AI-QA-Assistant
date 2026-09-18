"""Validate a submitted Gate C Claim sheet without impersonating its reviewer."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


HUMAN_COLUMNS = {"human_supported", "human_issue_type", "human_notes"}


def _rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def validate(sample_dir: Path, submission: Path, bundle: Path) -> dict:
    manifest = json.loads((sample_dir / "manifest.json").read_text(encoding="utf-8"))
    source_hash = hashlib.sha256((bundle / "04-final-claims.csv").read_bytes()).hexdigest()
    if source_hash != manifest["source_claims_sha256"]:
        raise ValueError("review sample refers to a different Claim bundle")
    original_fields, original = _rows(sample_dir / "claim-review-100.csv")
    submitted_fields, reviewed = _rows(submission)
    if submitted_fields != original_fields or len(reviewed) != len(original):
        raise ValueError("submitted Claim sheet has different columns or row count")
    if [row["claim_id"] for row in original] != manifest["selected_claim_ids"]:
        raise ValueError("frozen sample differs from its manifest")
    verdicts: list[bool] = []
    rejected: list[dict[str, str]] = []
    for expected, actual in zip(original, reviewed, strict=True):
        if any(actual[key] != expected[key] for key in original_fields if key not in HUMAN_COLUMNS):
            raise ValueError(f"submitted Claim or Evidence changed: {expected['claim_id']}")
        value = actual["human_supported"].strip().upper()
        if value not in {"TRUE", "FALSE", "YES", "NO"}:
            raise ValueError(f"missing or invalid verdict: {expected['claim_id']}")
        supported = value in {"TRUE", "YES"}
        issue_type = actual["human_issue_type"].strip()
        notes = actual["human_notes"].strip()
        if not notes or (supported and issue_type not in {"", "NONE"}) or (not supported and issue_type in {"", "NONE"}):
            raise ValueError(f"incomplete or inconsistent review fields: {expected['claim_id']}")
        verdicts.append(supported)
        if not supported:
            rejected.append({
                "claim_id": actual["claim_id"], "claim_text": actual["claim_text"],
                "issue_type": issue_type, "reviewer_notes": notes,
            })
    precision = sum(verdicts) / len(verdicts)
    return {
        "evaluation_label": "SUBMITTED_HUMAN_CLAIM_SHEET_CHECK",
        "status": "PARTIAL", "gate_c": "NOT_RUN",
        "revision": manifest["revision"],
        "sample_sha256": hashlib.sha256((sample_dir / "claim-review-100.csv").read_bytes()).hexdigest(),
        "submission_sha256": hashlib.sha256(submission.read_bytes()).hexdigest(),
        "sample_size": len(reviewed), "reviewed_rows": len(verdicts),
        "submitted_supported": sum(verdicts), "submitted_unsupported": len(rejected),
        "submitted_claim_precision": precision,
        "claim_precision_threshold_95": "PASS" if precision >= 0.95 else "PARTIAL",
        "reviewer_identity": "NOT_PROVIDED",
        "reviewer_attestation": "NOT_PROVIDED",
        "candidate_identity_page_human_checks": "NOT_RUN",
        "unsupported_claims": rejected,
        "limits": [
            "CSV integrity and arithmetic do not establish reviewer identity or independent human work",
            "100-Claim sample does not certify unsampled Claims",
            "Candidate, Identity, page and Evidence-location human criteria remain unscored",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-dir", required=True, type=Path)
    parser.add_argument("--submission", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite review report: {args.output}")
    result = validate(args.sample_dir, args.submission, args.bundle)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in (
        "status", "gate_c", "sample_size", "submitted_supported", "submitted_unsupported",
        "submitted_claim_precision", "claim_precision_threshold_95",
    )}, ensure_ascii=False))


if __name__ == "__main__":
    main()
