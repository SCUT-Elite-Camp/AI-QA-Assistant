"""Fork a reviewed subset of a draft Wiki revision without changing its evidence."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Collection

from storage.wiki_store import WikiStore


_REVISION_TABLES = (
    "wiki_build_documents", "wiki_candidates", "wiki_candidate_sources",
    "wiki_identities", "wiki_identity_aliases", "wiki_folders",
    "wiki_page_revisions", "wiki_page_claims", "wiki_page_sources",
    "wiki_page_links", "wiki_claim_audits", "wiki_claim_repairs",
)
_LINK = re.compile(r"\[([^\]]+)\]\(/wiki/([^)]*)\)")


def create_reviewed_revision(
    store: WikiStore, *, source_scope: str, owner_id: str, knowledge_base_id: str,
    source_revision: str, review_sha256: str, page_ids: Collection[str],
    identity_ids: Collection[str], candidate_ids: Collection[str],
    reviewer: str, reviewed_on: str,
) -> str:
    """Create a new DRAFT containing only explicitly approved navigation material.

    The caller must verify the human review and choose the IDs. This function
    keeps Claim text and Evidence bindings intact and never activates a revision.
    """
    if not re.fullmatch(r"[0-9a-f]{64}", review_sha256):
        raise ValueError("review digest must be SHA-256")
    if not reviewer.strip() or not reviewed_on.strip():
        raise ValueError("human reviewer and review date are required")
    pages, identities, candidates = map(set, (page_ids, identity_ids, candidate_ids))
    if not pages or any(not value for value in pages | identities | candidates):
        raise ValueError("reviewed Wiki release requires selected pages")
    scope, owner, kb = store._context(source_scope, owner_id, knowledge_base_id)
    source_key = (scope, owner, kb, source_revision)
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        run = db.execute(
            "SELECT status,input_hash,generator_model,prompt_version FROM wiki_build_runs "
            "WHERE source_scope=? AND owner_id=? AND knowledge_base_id=? AND revision=?",
            source_key,
        ).fetchone()
        if run is None or run["status"] != "DRAFT":
            raise ValueError("reviewed Wiki release requires an unchanged DRAFT")

        def available(table: str, column: str) -> set[str]:
            return {row[0] for row in db.execute(
                f"SELECT {column} FROM {table} WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND revision=?", source_key,
            )}

        if pages - available("wiki_page_revisions", "page_id"):
            raise ValueError("review selected an unknown page")
        if identities - available("wiki_identities", "identity_id"):
            raise ValueError("review selected an unknown identity")
        if candidates - available("wiki_candidates", "candidate_id"):
            raise ValueError("review selected an unknown candidate")
        selected_pages = db.execute(
            "SELECT page_id,page_type,identity_id,status FROM wiki_page_revisions WHERE "
            "source_scope=? AND owner_id=? AND knowledge_base_id=? AND revision=?",
            source_key,
        ).fetchall()
        for row in selected_pages:
            if row["page_id"] in pages and (row["status"] != "REVIEWING" or
                    row["identity_id"] and row["identity_id"] not in identities):
                raise ValueError("selected page is not approved for release")
        selected_identities = db.execute(
            "SELECT identity_id,candidate_ids FROM wiki_identities WHERE source_scope=? "
            "AND owner_id=? AND knowledge_base_id=? AND revision=?", source_key,
        ).fetchall()
        if any(not set(json.loads(row["candidate_ids"])) <= candidates
               for row in selected_identities if row["identity_id"] in identities):
            raise ValueError("selected identity contains an unapproved candidate")

        digest = hashlib.sha256(json.dumps({
            "source": source_revision, "input": run["input_hash"], "review": review_sha256,
            "pages": sorted(pages), "identities": sorted(identities),
            "candidates": sorted(candidates),
        }, sort_keys=True).encode()).hexdigest()
        revision = f"wr_review_{digest[:24]}"
        target_key = (scope, owner, kb, revision)
        if db.execute(
            "SELECT 1 FROM wiki_build_runs WHERE source_scope=? AND owner_id=? "
            "AND knowledge_base_id=? AND revision=?", target_key,
        ).fetchone():
            raise ValueError("reviewed Wiki revision already exists")
        db.execute(
            "INSERT INTO wiki_build_runs VALUES(?,?,?,?,?,?,?,?,?,NULL)",
            (*target_key, "DRAFT", digest, run["generator_model"],
             run["prompt_version"], int(time.time())),
        )
        db.execute(
            "INSERT INTO wiki_reviewed_releases VALUES(?,?,?,?,?,?,?,?,?)",
            (*target_key, source_revision, review_sha256, reviewer.strip(),
             reviewed_on.strip(), int(time.time())),
        )
        for table in _REVISION_TABLES:
            columns = [row["name"] for row in db.execute(f"PRAGMA table_info({table})")]
            projection = ",".join("?" if column == "revision" else column for column in columns)
            db.execute(
                f"INSERT INTO {table} ({','.join(columns)}) SELECT {projection} FROM {table} "
                "WHERE source_scope=? AND owner_id=? AND knowledge_base_id=? AND revision=?",
                (revision, *source_key),
            )

        def retain(table: str, column: str, selected: set[str]) -> None:
            placeholders = ",".join("?" for _ in selected) or "NULL"
            db.execute(
                f"DELETE FROM {table} WHERE source_scope=? AND owner_id=? "
                f"AND knowledge_base_id=? AND revision=? AND {column} NOT IN ({placeholders})",
                (*target_key, *sorted(selected)),
            )

        for table in ("wiki_candidates", "wiki_candidate_sources"):
            retain(table, "candidate_id", candidates)
        for table in ("wiki_identities", "wiki_identity_aliases"):
            retain(table, "identity_id", identities)
        for table in (
            "wiki_page_revisions", "wiki_page_claims", "wiki_page_sources",
            "wiki_page_links", "wiki_claim_audits", "wiki_claim_repairs",
        ):
            retain(table, "page_id", pages)

        slugs = {row["slug"] for row in db.execute(
            "SELECT slug FROM wiki_page_revisions WHERE source_scope=? AND owner_id=? "
            "AND knowledge_base_id=? AND revision=?", target_key,
        )}

        def unlink_missing(value: str) -> str:
            return _LINK.sub(
                lambda match: match.group(0) if match.group(2) in slugs else match.group(1),
                value,
            )

        for row in db.execute(
            "SELECT page_id,payload FROM wiki_page_revisions WHERE source_scope=? "
            "AND owner_id=? AND knowledge_base_id=? AND revision=?", target_key,
        ).fetchall():
            payload = json.loads(row["payload"])
            payload["links"] = sorted((set(payload.get("links") or []) & pages) - {row["page_id"]})
            payload["summary"] = unlink_missing(payload.get("summary") or "")
            for section in payload.get("sections") or []:
                for claim in section.get("claims") or []:
                    if any(match.group(2) not in slugs for match in _LINK.finditer(claim["text"])):
                        raise ValueError("approved Claim text contains a link to an excluded page")
                    claim["rendered_text"] = unlink_missing(claim.get("rendered_text") or "")
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            page_hash = hashlib.sha256(encoded.encode()).hexdigest()
            db.execute(
                "UPDATE wiki_page_revisions SET summary=?,payload=?,input_hash=? WHERE "
                "source_scope=? AND owner_id=? AND knowledge_base_id=? AND revision=? AND page_id=?",
                (payload["summary"], encoded, page_hash, *target_key, row["page_id"]),
            )
            db.execute(
                "DELETE FROM wiki_page_links WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND revision=? AND page_id=?",
                (*target_key, row["page_id"]),
            )
            db.executemany(
                "INSERT INTO wiki_page_links VALUES(?,?,?,?,?,?)",
                [(*target_key, row["page_id"], target) for target in payload["links"]],
            )
    return revision
