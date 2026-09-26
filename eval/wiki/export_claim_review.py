"""Export one private Wiki revision as a claim-to-Evidence review sheet."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export Wiki claim audit material")
    parser.add_argument("database", type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite review file: {args.output}")
    with sqlite3.connect(args.database) as db:
        db.row_factory = sqlite3.Row
        runs = db.execute(
            "SELECT source_scope,owner_id,knowledge_base_id FROM wiki_build_runs WHERE revision=?",
            (args.revision,),
        ).fetchall()
        if len(runs) != 1:
            raise ValueError("revision must resolve to exactly one Wiki scope")
        context = (runs[0]["source_scope"], runs[0]["owner_id"], runs[0]["knowledge_base_id"], args.revision)
        rows = db.execute(
            "SELECT r.title,r.page_type,c.page_id,c.section_heading,c.claim_id,c.claim_text,"
            "c.verdict,c.reason_code,c.reason,s.document_id,s.document_version_id,s.section_id,"
            "s.evidence_id,s.support_quote,s.quote_start,s.quote_end,s.evidence_sha256 "
            "FROM wiki_page_claims c JOIN wiki_page_revisions r ON r.source_scope=c.source_scope "
            "AND r.owner_id=c.owner_id AND r.knowledge_base_id=c.knowledge_base_id "
            "AND r.revision=c.revision AND r.page_id=c.page_id "
            "JOIN wiki_page_sources s ON s.source_scope=c.source_scope AND s.owner_id=c.owner_id "
            "AND s.knowledge_base_id=c.knowledge_base_id AND s.revision=c.revision "
            "AND s.page_id=c.page_id AND s.claim_id=c.claim_id WHERE c.source_scope=? "
            "AND c.owner_id=? AND c.knowledge_base_id=? AND c.revision=? "
            "ORDER BY r.title,c.section_heading,c.claim_id,s.source_id",
            context,
        ).fetchall()
    grouped: dict[str, dict] = {}
    for row in rows:
        item = grouped.setdefault(row["claim_id"], {
            "page_id": row["page_id"], "page_title": row["title"], "page_type": row["page_type"],
            "section_heading": row["section_heading"], "claim_id": row["claim_id"],
            "claim_text": row["claim_text"], "ai_verdict": row["verdict"],
            "ai_reason_code": row["reason_code"], "ai_reason": row["reason"], "sources": [],
            "human_supported": "", "human_issue_type": "", "human_notes": "",
        })
        item["sources"].append({key: row[key] for key in (
            "document_id", "document_version_id", "section_id", "evidence_id",
            "support_quote", "quote_start", "quote_end", "evidence_sha256",
        )})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "page_id", "page_title", "page_type", "section_heading", "claim_id", "claim_text",
        "ai_verdict", "ai_reason_code", "ai_reason", "sources_json",
        "human_supported", "human_issue_type", "human_notes",
    ]
    with args.output.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        for item in grouped.values():
            sources = item["sources"]
            writer.writerow({
                key: json.dumps(sources, ensure_ascii=False) if key == "sources_json" else item[key]
                for key in fields
            })
    print(json.dumps({"status": "EXPORTED", "claims": len(grouped), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
