from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from shared_runtime.knowledge_graph import KnowledgeEdge, KnowledgeNode, KnowledgeSource


class KnowledgeGraphStore:
    """Revisioned SQLite navigation graph with strict tenant scoping."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connection(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _initialize(self) -> None:
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS knowledge_graph_revisions (
                  source_scope TEXT NOT NULL,
                  owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL,
                  revision TEXT NOT NULL,
                  status TEXT NOT NULL,
                  input_hash TEXT NOT NULL,
                  generator_model TEXT NOT NULL DEFAULT '',
                  prompt_version TEXT NOT NULL DEFAULT '',
                  created_at INTEGER NOT NULL,
                  activated_at INTEGER,
                  PRIMARY KEY(source_scope,owner_id,knowledge_base_id,revision)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS knowledge_graph_one_active
                  ON knowledge_graph_revisions(source_scope,owner_id,knowledge_base_id)
                  WHERE status='active';
                CREATE TABLE IF NOT EXISTS knowledge_nodes (
                  source_scope TEXT NOT NULL,
                  owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL,
                  revision TEXT NOT NULL,
                  id TEXT NOT NULL,
                  node_type TEXT NOT NULL,
                  canonical_name TEXT NOT NULL,
                  aliases TEXT NOT NULL,
                  description TEXT NOT NULL,
                  metadata TEXT NOT NULL,
                  PRIMARY KEY(source_scope,owner_id,knowledge_base_id,revision,id)
                );
                CREATE TABLE IF NOT EXISTS knowledge_edges (
                  source_scope TEXT NOT NULL,
                  owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL,
                  revision TEXT NOT NULL,
                  id TEXT NOT NULL,
                  source_node_id TEXT NOT NULL,
                  target_node_id TEXT NOT NULL,
                  relation_type TEXT NOT NULL,
                  description TEXT NOT NULL,
                  metadata TEXT NOT NULL,
                  PRIMARY KEY(source_scope,owner_id,knowledge_base_id,revision,id)
                );
                CREATE TABLE IF NOT EXISTS knowledge_sources (
                  source_scope TEXT NOT NULL,
                  owner_id TEXT NOT NULL,
                  knowledge_base_id TEXT NOT NULL,
                  revision TEXT NOT NULL,
                  target_kind TEXT NOT NULL,
                  target_id TEXT NOT NULL,
                  document_version_id TEXT NOT NULL,
                  section_id TEXT NOT NULL,
                  evidence_id TEXT NOT NULL,
                  support_span TEXT NOT NULL,
                  PRIMARY KEY(
                    source_scope,owner_id,knowledge_base_id,revision,target_kind,
                    target_id,document_version_id,evidence_id
                  )
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_nodes_fts USING fts5(
                  target_id UNINDEXED,
                  source_scope UNINDEXED,
                  owner_id UNINDEXED,
                  knowledge_base_id UNINDEXED,
                  revision UNINDEXED,
                  search_text
                );
            """)

    @staticmethod
    def _context(source_scope: str, owner_id: str, knowledge_base_id: str) -> tuple[str, str, str]:
        scope = source_scope.casefold().strip()
        owner = owner_id.strip()
        kb = knowledge_base_id.strip()
        if scope not in {"enterprise", "personal"}:
            raise ValueError("source_scope must be enterprise or personal")
        if not kb:
            raise ValueError("knowledge_base_id is required")
        if scope == "personal" and not owner:
            raise ValueError("personal graph access requires owner_id")
        if scope == "enterprise":
            owner = ""
        return scope, owner, kb

    def replace_revision(
        self,
        *,
        source_scope: str,
        owner_id: str,
        knowledge_base_id: str,
        revision: str,
        input_hash: str,
        nodes: Iterable[KnowledgeNode | dict[str, Any]],
        edges: Iterable[KnowledgeEdge | dict[str, Any]],
        sources: Iterable[KnowledgeSource | dict[str, Any]],
        generator_model: str = "",
        prompt_version: str = "",
    ) -> None:
        scope, owner, kb = self._context(source_scope, owner_id, knowledge_base_id)
        revision = revision.strip()
        if not revision or not input_hash.strip():
            raise ValueError("revision and input_hash are required")
        node_rows = [value if isinstance(value, KnowledgeNode) else KnowledgeNode.model_validate(value) for value in nodes]
        edge_rows = [value if isinstance(value, KnowledgeEdge) else KnowledgeEdge.model_validate(value) for value in edges]
        source_rows = [value if isinstance(value, KnowledgeSource) else KnowledgeSource.model_validate(value) for value in sources]
        node_ids = {item.id for item in node_rows}
        edge_ids = {item.id for item in edge_rows}
        if len(node_ids) != len(node_rows) or len(edge_ids) != len(edge_rows):
            raise ValueError("knowledge graph IDs must be unique within a revision")
        if any(edge.source_node_id not in node_ids or edge.target_node_id not in node_ids for edge in edge_rows):
            raise ValueError("every knowledge edge must reference nodes in the same revision")
        sourced = {(item.target_kind, item.target_id) for item in source_rows}
        missing = [
            target for target in [
                *(("node", value) for value in sorted(node_ids)),
                *(("edge", value) for value in sorted(edge_ids)),
            ] if target not in sourced
        ]
        if missing:
            raise ValueError("every published graph node and edge requires Evidence provenance")
        if any(
            (item.target_kind == "node" and item.target_id not in node_ids)
            or (item.target_kind == "edge" and item.target_id not in edge_ids)
            for item in source_rows
        ):
            raise ValueError("knowledge source references an unknown graph target")

        now = int(time.time())
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            key = (scope, owner, kb, revision)
            old_targets = db.execute(
                "SELECT id FROM knowledge_nodes WHERE source_scope=? AND owner_id=? "
                "AND knowledge_base_id=? AND revision=?", key,
            ).fetchall()
            for row in old_targets:
                db.execute(
                    "DELETE FROM knowledge_nodes_fts WHERE target_id=? AND source_scope=? "
                    "AND owner_id=? AND knowledge_base_id=? AND revision=?",
                    (row["id"], scope, owner, kb, revision),
                )
            for table in ("knowledge_sources", "knowledge_edges", "knowledge_nodes", "knowledge_graph_revisions"):
                db.execute(
                    f"DELETE FROM {table} WHERE source_scope=? AND owner_id=? "
                    "AND knowledge_base_id=? AND revision=?", key,
                )
            db.execute(
                "INSERT INTO knowledge_graph_revisions VALUES(?,?,?,?,?,?,?,?,?,NULL)",
                (scope, owner, kb, revision, "pending", input_hash, generator_model, prompt_version, now),
            )
            for node in node_rows:
                db.execute(
                    "INSERT INTO knowledge_nodes VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (scope, owner, kb, revision, node.id, node.node_type.value,
                     node.canonical_name, json.dumps(node.aliases, ensure_ascii=False),
                     node.description, json.dumps(node.metadata, ensure_ascii=False)),
                )
                search_text = "\n".join([node.canonical_name, *node.aliases, node.description])
                db.execute(
                    "INSERT INTO knowledge_nodes_fts VALUES(?,?,?,?,?,?)",
                    (node.id, scope, owner, kb, revision, search_text),
                )
            for edge in edge_rows:
                db.execute(
                    "INSERT INTO knowledge_edges VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (scope, owner, kb, revision, edge.id, edge.source_node_id,
                     edge.target_node_id, edge.relation_type.value, edge.description,
                     json.dumps(edge.metadata, ensure_ascii=False)),
                )
            for source in source_rows:
                db.execute(
                    "INSERT INTO knowledge_sources VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (scope, owner, kb, revision, source.target_kind, source.target_id,
                     source.document_version_id, source.section_id, source.evidence_id,
                     json.dumps(source.support_span, ensure_ascii=False)),
                )
            db.execute(
                "UPDATE knowledge_graph_revisions SET status='stale' WHERE source_scope=? "
                "AND owner_id=? AND knowledge_base_id=? AND status='active'", (scope, owner, kb),
            )
            db.execute(
                "UPDATE knowledge_graph_revisions SET status='active',activated_at=? "
                "WHERE source_scope=? AND owner_id=? AND knowledge_base_id=? AND revision=?",
                (now, scope, owner, kb, revision),
            )

    def search(
        self,
        query: str,
        *,
        source_scope: str,
        owner_id: str,
        knowledge_base_id: str,
        top_k: int = 8,
    ) -> list[dict[str, Any]]:
        scope, owner, kb = self._context(source_scope, owner_id, knowledge_base_id)
        query = query.strip()
        if not query:
            return []
        top_k = min(20, max(1, int(top_k)))
        with self.connection() as db:
            active = db.execute(
                "SELECT revision FROM knowledge_graph_revisions WHERE source_scope=? "
                "AND owner_id=? AND knowledge_base_id=? AND status='active'",
                (scope, owner, kb),
            ).fetchone()
            if not active:
                return []
            revision = str(active["revision"])
            terms = [value.replace('"', "") for value in query.split() if value][:20]
            rows: list[sqlite3.Row] = []
            if terms:
                expression = " OR ".join(f'"{value}"' for value in terms)
                try:
                    rows = db.execute(
                        "SELECT target_id,bm25(knowledge_nodes_fts) AS rank "
                        "FROM knowledge_nodes_fts WHERE knowledge_nodes_fts MATCH ? "
                        "AND source_scope=? AND owner_id=? AND knowledge_base_id=? AND revision=? "
                        "ORDER BY rank LIMIT ?",
                        (expression, scope, owner, kb, revision, top_k),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            if rows:
                ids = [str(row["target_id"]) for row in rows]
            else:
                like = f"%{query.casefold()}%"
                fallback = db.execute(
                    "SELECT id FROM knowledge_nodes WHERE source_scope=? AND owner_id=? "
                    "AND knowledge_base_id=? AND revision=? AND lower(canonical_name || ' ' || aliases || ' ' || description) LIKE ? "
                    "ORDER BY canonical_name,id LIMIT ?",
                    (scope, owner, kb, revision, like, top_k),
                ).fetchall()
                ids = [str(row["id"]) for row in fallback]
            return [
                self._navigation_row(db, scope, owner, kb, revision, node_id, rank)
                for rank, node_id in enumerate(ids, 1)
            ]

    @staticmethod
    def _navigation_row(
        db: sqlite3.Connection,
        scope: str,
        owner: str,
        kb: str,
        revision: str,
        node_id: str,
        rank: int,
    ) -> dict[str, Any]:
        node = db.execute(
            "SELECT * FROM knowledge_nodes WHERE source_scope=? AND owner_id=? "
            "AND knowledge_base_id=? AND revision=? AND id=?",
            (scope, owner, kb, revision, node_id),
        ).fetchone()
        sources = db.execute(
            "SELECT document_version_id,section_id,evidence_id FROM knowledge_sources "
            "WHERE source_scope=? AND owner_id=? AND knowledge_base_id=? AND revision=? "
            "AND target_kind='node' AND target_id=?",
            (scope, owner, kb, revision, node_id),
        ).fetchall()
        edges = db.execute(
            "SELECT id,source_node_id,target_node_id,relation_type,description FROM knowledge_edges "
            "WHERE source_scope=? AND owner_id=? AND knowledge_base_id=? AND revision=? "
            "AND (source_node_id=? OR target_node_id=?) ORDER BY id LIMIT 20",
            (scope, owner, kb, revision, node_id, node_id),
        ).fetchall()
        return {
            "id": node_id,
            "node_type": node["node_type"],
            "canonical_name": node["canonical_name"],
            "aliases": json.loads(node["aliases"] or "[]"),
            "description": node["description"],
            "score": round(1.0 / (1.0 + 0.12 * (rank - 1)), 6),
            "document_version_ids": list(dict.fromkeys(row["document_version_id"] for row in sources)),
            "section_ids": list(dict.fromkeys(row["section_id"] for row in sources if row["section_id"])),
            "evidence_ids": list(dict.fromkeys(row["evidence_id"] for row in sources)),
            "edges": [dict(row) for row in edges],
            "citation_authority": False,
        }

    def mark_stale_for_document_version(self, document_version_id: str) -> int:
        """Stale every active revision that cites an invalidated document version."""
        with self.connection() as db:
            cursor = db.execute(
                "UPDATE knowledge_graph_revisions SET status='stale' WHERE status='active' "
                "AND EXISTS(SELECT 1 FROM knowledge_sources s WHERE "
                "s.source_scope=knowledge_graph_revisions.source_scope AND "
                "s.owner_id=knowledge_graph_revisions.owner_id AND "
                "s.knowledge_base_id=knowledge_graph_revisions.knowledge_base_id AND "
                "s.revision=knowledge_graph_revisions.revision AND s.document_version_id=?)",
                (document_version_id,),
            )
            return int(cursor.rowcount)
