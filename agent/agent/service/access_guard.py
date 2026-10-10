"""Request-local access and transitive evidence dependency enforcement.

No positive decision is cached. Tool output is checked before entering model
context; inherited and newly read dependencies are rechecked before each model
call and before releasing a buffered response.
"""
from __future__ import annotations

import time
from contextvars import ContextVar
from threading import RLock
from typing import Any

from agent.schemas.chat import EvidenceProvenance, InternalChatRequest, SourceDependency
from agent.service.permission_service import PermissionResolutionError


CURRENT_ACCESS_GUARD: ContextVar["AccessGuard | None"] = ContextVar("agent_access_guard", default=None)


def check_model_access() -> None:
    guard = CURRENT_ACCESS_GUARD.get()
    if guard is not None:
        guard.check_dependencies()


class AccessGuard:
    def __init__(self, permission_service, request, trace_id: str):
        self.permissions = permission_service
        self.request = request
        self.user_id = request.user_id or ""
        self.trace_id = trace_id
        self._dependencies: dict[tuple, SourceDependency] = {}
        self._lock = RLock()

    def allowed_documents(self, doc_ids: list[str] | None = None) -> list[str]:
        return self.permissions.get_accessible_doc_ids_strict(self.user_id, doc_ids=doc_ids)

    def sanitize_request(self):
        # Validate the enabled actor even for direct answers without retrieval.
        self.allowed_documents([])
        updates = {"soul_content": None, "topic_titles": None, "topic_doc_ids": None}
        if isinstance(self.request, InternalChatRequest):
            context = self.request.memory_context
            if context.actor.user_id != self.user_id or context.chat_id != self.request.session_id:
                raise PermissionResolutionError("trusted_actor_mismatch", 403)
            tail = []
            for item in context.tail:
                if item.provenance_complete and self._inherit_if_allowed(item.source_dependencies):
                    tail.append(item)
            snapshot = context.snapshot
            if snapshot is not None and (not snapshot.provenance_complete or not self._inherit_if_allowed(snapshot.source_dependencies)):
                snapshot = None
            facts = [item for item in context.facts if item.provenance_complete and self._inherit_if_allowed(item.source_dependencies)]
            if context.provenance_complete:
                # Includes derived workspace context, not merely final citations.
                if self._inherit_if_allowed(context.source_dependencies):
                    updates.update(soul_content=self.request.soul_content, topic_titles=self.request.topic_titles, topic_doc_ids=self.request.topic_doc_ids)
            updates["memory_context"] = context.model_copy(update={"tail": tail, "snapshot": snapshot, "facts": facts})
            library = self.request.personal_library_context
            if library is not None and library.owner_user_id != self.user_id:
                raise PermissionResolutionError("private_source_forbidden", 403)
        return self.request.model_copy(update=updates)

    def _inherit_if_allowed(self, dependencies) -> bool:
        try:
            for dependency in dependencies:
                self._check_one(dependency)
        except PermissionResolutionError as exc:
            if exc.status_code in {403, 404, 409}:
                return False
            raise
        for dependency in dependencies:
            self._add(dependency)
        return True

    def _add(self, dependency: SourceDependency):
        key = (dependency.source_type, dependency.doc_id, dependency.knowledge_base_id, dependency.version_id, dependency.version, dependency.content_hash)
        with self._lock:
            self._dependencies[key] = dependency

    def prepare_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.check_dependencies()
        arguments = dict(arguments)
        if name in {"search_documents", "find_documents"}:
            filters = dict(arguments.get("filters") or {})
            candidates = filters.get("doc_ids", filters.get("doc_id"))
            if isinstance(candidates, str):
                candidates = [candidates]
            filters.pop("doc_id", None)
            filters["doc_ids"] = self.allowed_documents(candidates)
            arguments["filters"] = filters
        elif name == "get_document":
            doc_id = str(arguments.get("doc_id") or "")
            if doc_id not in self.allowed_documents([doc_id]):
                raise PermissionResolutionError("source_not_found", 404)
        elif name in {"browse_document_outline", "search_evidence_in_scope"} and arguments.get("source_scope", "enterprise") == "enterprise":
            arguments["doc_ids"] = self.allowed_documents(arguments.get("doc_ids"))
        elif name == "inspect_attachment":
            context = getattr(self.request, "attachment_context", None)
            if context is None or arguments.get("attachment_id") not in context.allowed_attachment_ids:
                raise PermissionResolutionError("private_source_not_found", 404)
            # This tool can send bytes to a vision model. An allowlist alone is
            # not a current grant: check ownership/scope/version before I/O.
            with self.permissions._connect() as connection:
                self._authorize_attachment(connection, str(arguments["attachment_id"]))
        elif name.startswith("wiki_"):
            # Derived Wiki pages have no complete transitive lineage contract yet.
            # Never pass their titles/summaries to the model as authorized context.
            raise PermissionResolutionError("wiki_provenance_unavailable", 503)
        return arguments

    def capture_tool(self, name: str, data: dict | None, evidence: list):
        records = [item.model_dump() for item in evidence]
        data = data or {}
        for key in ("documents", "sections", "items"):
            records.extend(item for item in data.get(key, []) if isinstance(item, dict))
        if isinstance(data.get("document"), dict):
            records.append(data["document"])
        for record in records:
            doc_id = str(record.get("doc_id") or record.get("document_id") or record.get("attachment_id") or "")
            if not doc_id:
                if any(record.get(key) for key in ("content", "text", "summary", "title")):
                    raise PermissionResolutionError("source_provenance_unavailable", 503)
                continue
            source_type = "personal" if record.get("source_scope") == "personal" or record.get("source_type") == "personal" or name == "search_library" else "attachment" if record.get("attachment_id") or name in {"search_attachments", "inspect_attachment"} else "knowledge"
            values = {key: record.get(key) for key in ("knowledge_base_id", "document_id", "version_id", "content_hash")}
            values["version"] = record.get("source_version") or record.get("version")
            if source_type == "knowledge":
                actual = self._knowledge_snapshot(doc_id)
                document = self.permissions.source_provider._load(doc_id)
                text = record.get("content") or record.get("chunk_text") or record.get("text") or record.get("snippet") or record.get("match_summary")
                # Discovery may return a title when no content passage matched.
                # This is metadata, not an original excerpt; only the exact
                # current title is permitted, and only for discovery records.
                title_only = name == "find_documents" and str(record.get("chunk_id") or "").endswith("::document") and text == document.get("title")
                if text and not title_only and not self._matches_original(str(text), document):
                    raise PermissionResolutionError("source_evidence_changed", 409)
                if record.get("title") and record["title"] != document.get("title"):
                    raise PermissionResolutionError("source_evidence_changed", 409)
                if values["content_hash"] is not None and values["content_hash"] != actual.get("content_hash"):
                    raise PermissionResolutionError("document_version_changed", 409)
                if values["version"] is not None and str(values["version"]) != str(actual.get("source_version")):
                    raise PermissionResolutionError("document_version_changed", 409)
                values["version"] = actual.get("source_version")
                values["content_hash"] = actual.get("content_hash")
            dependency = SourceDependency(source_type=source_type, doc_id=doc_id, **values)
            self._add(dependency)
        self.check_dependencies()

    def _knowledge_snapshot(self, doc_id: str) -> dict:
        from toolset.tool_layer.evidence_metadata import source_metadata
        document = self.permissions.source_provider._load(doc_id)
        if document is None:
            raise PermissionResolutionError("source_not_found", 404)
        metadata = source_metadata(document)
        if not metadata.get("content_hash"):
            raise PermissionResolutionError("source_provenance_unavailable", 503)
        return metadata

    @staticmethod
    def _matches_original(text: str, document: dict) -> bool:
        # Missing index provenance never licenses rebinding stale text to the
        # current version. Compare against the actual source projection first.
        body = str(document.get("content") or "")
        if text.strip() and text.strip() in body:
            return True
        return any(bool(text.strip()) and text.strip() in str(c.get("text") or c.get("chunk_text") or "").strip()
                   for c in document.get("chunks", []) if isinstance(c, dict))

    def _check_one(self, dependency: SourceDependency, *, permission_checked: bool = False):
        if dependency.source_type == "knowledge":
            if not permission_checked and dependency.doc_id not in self.allowed_documents([dependency.doc_id]):
                raise PermissionResolutionError("source_not_found", 404)
            current = self._knowledge_snapshot(dependency.doc_id)
            if not dependency.content_hash:
                raise PermissionResolutionError("source_provenance_unavailable", 403)
            if dependency.content_hash != current.get("content_hash") or (dependency.version is not None and str(dependency.version) != str(current.get("source_version"))):
                raise PermissionResolutionError("document_version_changed", 409)
            return
        try:
            with self.permissions._connect() as connection:
                # Do not allow a disabled actor to use private-source-only recall.
                actor = connection.execute("SELECT disabled FROM users WHERE id=?", (self.user_id,)).fetchone()
                if actor is None or bool(actor[0]):
                    raise PermissionResolutionError("actor_forbidden", 403)
                if dependency.source_type == "personal":
                    if not dependency.knowledge_base_id or not dependency.version_id or not dependency.content_hash:
                        raise PermissionResolutionError("source_provenance_unavailable", 403)
                    row = connection.execute("SELECT owner_user_id,knowledge_base_id,deleted_at,active_version_id,source_scope FROM library_documents WHERE id=?", (dependency.document_id or dependency.doc_id,)).fetchone()
                    if row is None or row[4] != "personal" or row[0] != self.user_id or row[2] is not None or not row[3] or row[1] != dependency.knowledge_base_id:
                        raise PermissionResolutionError("private_source_not_found", 404)
                    if dependency.version_id and row[3] != dependency.version_id:
                        raise PermissionResolutionError("document_version_changed", 409)
                    library = connection.execute("SELECT owner_user_id,deleted_at FROM knowledge_bases WHERE id=?", (row[1],)).fetchone()
                    version = connection.execute("SELECT content_hash,status FROM document_versions WHERE id=?", (row[3],)).fetchone()
                    if library is None or library[0] != self.user_id or library[1] is not None or version is None or version[1] != "READY":
                        raise PermissionResolutionError("private_source_not_found", 404)
                    if dependency.content_hash and version[0] != dependency.content_hash:
                        raise PermissionResolutionError("document_version_changed", 409)
                    storage = connection.execute("SELECT storage_ref FROM document_versions WHERE id=?", (row[3],)).fetchone()
                    remote = self._private_source(storage[0])
                    if remote.get("owner_id") != self.user_id or remote.get("knowledge_base_id") != dependency.knowledge_base_id or remote.get("source_scope") != "personal" or remote.get("scope") != "library" or remote.get("status") != "ready" or remote.get("document_id") != (dependency.document_id or dependency.doc_id) or remote.get("version_id") != row[3] or not remote.get("active") or remote.get("sha256") != dependency.content_hash:
                        raise PermissionResolutionError("document_version_changed", 409)
                else:
                    attachment_id = dependency.doc_id.removeprefix("attachment:")
                    row, remote = self._authorize_attachment(connection, attachment_id)
                    if not dependency.content_hash or dependency.version is None:
                        raise PermissionResolutionError("source_provenance_unavailable", 403)
                    if dependency.version is not None and str(row[5]) != str(dependency.version):
                        raise PermissionResolutionError("document_version_changed", 409)
                    if str(remote.get("evidence_version")) != str(dependency.version):
                        raise PermissionResolutionError("document_version_changed", 409)
                    evidence = self._private_source(attachment_id, evidence=True)
                    if not any(item.get("content_hash") == dependency.content_hash for item in evidence.get("items", [])):
                        raise PermissionResolutionError("document_version_changed", 409)
        except PermissionResolutionError:
            raise
        except Exception as exc:
            raise PermissionResolutionError("private_source_permission_unavailable", 503) from exc

    def _authorize_attachment(self, connection, attachment_id: str):
        row = connection.execute("SELECT owner_id,scope,chat_id,topic_id,status,evidence_version,expires_at,deleted_at FROM attachments WHERE id=?", (attachment_id,)).fetchone()
        # Drizzle integer(timestamp) and the attachment service use epoch seconds.
        if row is None or row[7] is not None or (row[1] != "topic" and row[6] is not None and int(row[6]) <= int(time.time())) or row[4] not in {"ready", "needs_review"}:
            raise PermissionResolutionError("private_source_not_found", 404)
        context = getattr(self.request, "attachment_context", None)
        allowed_ids = context.allowed_attachment_ids if context else []
        allowed = row[0] == self.user_id and (row[1] == "draft" and attachment_id in allowed_ids or row[1] == "chat" and row[2] == self.request.session_id)
        if row[1] == "topic" and row[3] == self.request.topic_id:
            allowed = connection.execute("SELECT 1 FROM topic_members WHERE topic_id=? AND user_id=?", (row[3], self.user_id)).fetchone() is not None
        if not allowed:
            raise PermissionResolutionError("private_source_not_found", 404)
        remote = self._private_source(attachment_id)
        if remote.get("status") not in {"ready", "needs_review"} or remote.get("owner_id") != row[0] or remote.get("scope") != row[1] or remote.get("chat_id") != row[2] or remote.get("topic_id") != row[3] or str(remote.get("evidence_version")) != str(row[5]):
            raise PermissionResolutionError("document_version_changed", 409)
        return row, remote

    @staticmethod
    def _private_source(storage_id: str, *, evidence: bool = False) -> dict:
        import os
        import json
        from urllib.parse import quote
        import requests
        secret = os.getenv("ATTACHMENT_INTERNAL_SECRET", "")
        if not secret:
            raise PermissionResolutionError("private_source_permission_unavailable", 503)
        endpoint = os.getenv("ATTACHMENT_SERVICE_URL", "http://127.0.0.1:8200").rstrip("/") + "/v1/attachments/" + quote(storage_id, safe="") + ("/evidence" if evidence else "")
        try:
            response = requests.get(endpoint, headers={"Authorization": "Bearer " + secret}, timeout=8, allow_redirects=False)
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError("private_source_redirect_or_invalid_response")
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("private_source_response_invalid")
            return result
        except Exception as exc:
            raise PermissionResolutionError("private_source_permission_unavailable", 503) from exc

    def check_dependencies(self):
        self.allowed_documents([])
        with self._lock:
            dependencies = list(self._dependencies.values())
        # Batch only within this check boundary, never reuse a positive grant
        # across tool/model/persistence boundaries. Multiple chunks from one
        # source must not issue duplicate upstream checks in the same phase.
        knowledge_ids = list(dict.fromkeys(d.doc_id for d in dependencies if d.source_type == "knowledge"))
        if knowledge_ids and set(knowledge_ids) != set(self.allowed_documents(knowledge_ids)):
            raise PermissionResolutionError("source_not_found", 404)
        for dependency in dependencies:
            self._check_one(dependency, permission_checked=True)

    def provenance(self) -> EvidenceProvenance:
        self.check_dependencies()
        with self._lock:
            dependencies = list(self._dependencies.values())
        return EvidenceProvenance(complete=True, dependencies=dependencies, trace_id=self.trace_id)
