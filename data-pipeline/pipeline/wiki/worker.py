"""Durable stage worker for scope-wide Wiki rebuilds after document lifecycle events."""

from __future__ import annotations

import time
import threading
from typing import Any, Callable

from .domain import (
    CandidateStatus, PromotionStatus, RevisionStatus, WikiBuildArtifact,
    WikiBuildDocument, WikiCandidate, WikiClaimAuditRecord, WikiClaimRepairRecord,
    WikiFolder, WikiIdentity, WikiIssue, WikiPageDraft, WikiPlacement, WikiScope,
    WikiSourceDocument,
)
from .finalize import finalize_wiki_pages
from .job import (
    WikiBuildService, _build_input_hash, _cached_page_matches_audit, _context,
    _prune_identities, _combined_prompt_version,
)
from .quality import build_source_catalog
from .queue import WikiJobStage, next_wiki_stage
from .search import BgeM3WikiVectorSearch


class WikiStageWorker:
    """Run one persisted stage at a time using an authoritative active-document loader.

    The loader returns every active Wiki source document in the leased scope. A
    changed document set invalidates the checkpoint; a later job can rebuild it.
    """

    def __init__(
        self, service: WikiBuildService,
        load_active_documents: Callable[[dict[str, Any]], list[WikiSourceDocument]],
        *, worker_id: str, vector_indexer: BgeM3WikiVectorSearch | None = None,
        scope_filter: WikiScope | None = None,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("Wiki worker_id is required")
        self.service = service
        self.repository = service.repository
        self.load_active_documents = load_active_documents
        self.worker_id = worker_id
        self.vector_indexer = vector_indexer
        self.scope_filter = scope_filter

    def run_once(self) -> bool:
        if not self.service.config.enabled:
            raise RuntimeError("WIKI_INGEST_ENABLED is false")
        lease = self.repository.lease_wiki_job(
            worker_id=self.worker_id, lease_seconds=600,
            **(_context(self.scope_filter) if self.scope_filter else {}),
        )
        if lease is None:
            return False
        job_id = lease["job_id"]
        stage = WikiJobStage(lease["stage"])
        state = dict(lease["payload"])
        stop_heartbeat = threading.Event()
        lease_lost = threading.Event()
        def heartbeat() -> None:
            while not stop_heartbeat.wait(60):
                try:
                    if not self.repository.renew_wiki_job_lease(
                        job_id, worker_id=self.worker_id, attempt=lease["attempt"],
                        lease_seconds=600,
                    ):
                        lease_lost.set()
                        return
                except Exception:
                    # The next tick may recover a transient SQLite lock.
                    continue
        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        guard = (job_id, self.worker_id, lease["attempt"])
        try:
            documents = list(self.load_active_documents(lease))
            if state.get("document_order"):
                by_version = {item.document_version_id: item for item in documents}
                if set(by_version) != set(state["document_order"]):
                    raise ValueError("Wiki worker source versions changed during staged build")
                documents = [by_version[version] for version in state["document_order"]]
            else:
                state["document_order"] = [item.document_version_id for item in documents]
            scope = WikiScope(source_scope=lease["source_scope"], owner_id=lease["owner_id"],
                              knowledge_base_id=lease["knowledge_base_id"])
            if any(document.scope != scope for document in documents):
                raise ValueError("Wiki worker loader returned a document from another scope")
            if len({document.document_id for document in documents}) != len(documents):
                raise ValueError("Wiki worker loader returned multiple active versions of a document")
            active_by_id = {document.document_id: document for document in documents}
            for change in state.get("changes") or []:
                current = active_by_id.get(change["document_id"])
                if change["op_type"] == "DELETE":
                    if current is not None:
                        raise ValueError("Wiki deletion is not reflected in active documents")
                elif (current is None or current.document_version_id != change["document_version_id"]
                      or current.content_sha256 != change["content_sha256"]):
                    raise ValueError("Wiki update is not reflected in active documents")
            input_hash = _build_input_hash(documents, self.service)
            if state.get("input_hash") and state["input_hash"] != input_hash:
                raise ValueError("Wiki worker source snapshot changed during staged build")
            state.setdefault("input_hash", input_hash)
            state.setdefault("revision", f"wr_{input_hash[:24]}")
            if stage == WikiJobStage.EXTRACT:
                if self.repository.reusable_revision(input_hash=input_hash, **_context(scope)):
                    self.repository.advance_wiki_job(job_id, worker_id=self.worker_id,
                                                     next_stage=None, payload={"reused": True},
                                                     attempt=lease["attempt"])
                    return True
                candidates: list[WikiCandidate] = []
                issues: list[WikiIssue] = []
                for document in documents:
                    cached = self.repository.load_published_candidates(
                        document.document_version_id, **_context(scope),
                    )
                    if cached is None:
                        extracted = self.service.extractor.extract(document)
                        candidates.extend(extracted.candidates)
                        issues.extend(extracted.issues)
                    else:
                        values = [WikiCandidate.model_validate(item) for item in cached]
                        if any(item.scope != scope for item in values):
                            raise ValueError("cached Wiki candidates cross the current scope")
                        candidates.extend(values)
                state["candidates"] = _dump(candidates)
                state["issues"] = _dump(issues)
            elif stage == WikiJobStage.CITE:
                evidence = {(document.document_version_id, chunk.evidence_id): chunk
                            for document in documents for chunk in document.chunks}
                for candidate in _load(WikiCandidate, state["candidates"]):
                    for source in candidate.sources:
                        chunk = evidence.get((source.document_version_id, source.evidence_id))
                        if (chunk is None or chunk.text_sha256 != source.evidence_sha256
                                or chunk.text[source.quote_start:source.quote_end] != source.support_quote):
                            raise ValueError("Wiki worker Evidence binding is not authoritative")
            elif stage == WikiJobStage.PROMOTE:
                candidates, issues = self.service.promotion_selector.select(
                    _load(WikiCandidate, state["candidates"]),
                )
                state["candidates"] = _dump(candidates)
                state["issues"].extend(_dump(issues))
            elif stage == WikiJobStage.RESOLVE:
                candidates = _load(WikiCandidate, state["candidates"])
                promoted = [item for item in candidates
                            if item.status == CandidateStatus.EVIDENCE_BOUND
                            and item.promotion_status == PromotionStatus.PROMOTED]
                existing = _prune_identities(_load(WikiIdentity,
                    self.repository.load_published_identities(**_context(scope))), promoted)
                identities, issues = self.service.identity_resolver.resolve_with_issues(
                    promoted, existing=existing,
                ) if promoted else ([], [])
                state["identities"] = _dump(identities)
                state["issues"].extend(_dump(issues))
            elif stage == WikiJobStage.COMPILE:
                identities = _load(WikiIdentity, state["identities"])
                candidates = _load(WikiCandidate, state["candidates"])
                if identities:
                    folder_values, placement_values = self.repository.load_published_taxonomy(**_context(scope))
                    folders, placements = self.service.taxonomy_planner.plan(
                        identities, existing_folders=_load(WikiFolder, folder_values),
                        existing_placements=[item for item in _load(WikiPlacement, placement_values)
                                             if item.identity_id in {identity.id for identity in identities}],
                    )
                    raw_audits = self.repository.load_published_page_audit_cache(**_context(scope))
                    page_cache = {key: page for key, value in
                                  self.repository.load_published_page_cache(**_context(scope)).items()
                                  if _cached_page_matches_audit(
                                      page := WikiPageDraft.model_validate(value), raw_audits.get(key) or {},
                                      quality_tag=self.service.quality_gate.cache_tag)}
                    pages = self.service.page_compiler.compile(
                        documents, [item for item in candidates if item.status == CandidateStatus.EVIDENCE_BOUND],
                        identities, folders, placements, page_cache=page_cache,
                    )
                else:
                    folders, pages = [], []
                state["folders"] = _dump(folders)
                state["pages"] = _dump(pages)
            elif stage == WikiJobStage.VERIFY:
                candidates = _load(WikiCandidate, state["candidates"])
                sources = build_source_catalog(documents, [item for item in candidates
                                                       if item.status == CandidateStatus.EVIDENCE_BOUND])
                raw_audits = self.repository.load_published_page_audit_cache(**_context(scope))
                raw_pages = self.repository.load_published_page_cache(**_context(scope))
                verified, audits, repairs = [], [], []
                for page in _load(WikiPageDraft, state["pages"]):
                    old = raw_pages.get(page.input_hash)
                    trace = raw_audits.get(page.input_hash) or {}
                    if old and _cached_page_matches_audit(
                        WikiPageDraft.model_validate(old), trace,
                        quality_tag=self.service.quality_gate.cache_tag,
                    ):
                        page.status = RevisionStatus.REVIEWING
                        verified.append(page)
                        audits.extend(_load(WikiClaimAuditRecord, trace.get("audits") or []))
                        repairs.extend(_load(WikiClaimRepairRecord, trace.get("repairs") or []))
                    else:
                        result = self.service.quality_gate.verify(page, sources, documents)
                        verified.append(result.page)
                        audits.extend(result.audits)
                        repairs.extend(result.repairs)
                        state["issues"].extend(_dump(result.issues))
                state["pages"] = _dump(verified)
                state["audits"] = _dump(audits)
                state["repairs"] = _dump(repairs)
            elif stage == WikiJobStage.FINALIZE:
                candidates = _load(WikiCandidate, state["candidates"])
                pages = finalize_wiki_pages(_load(WikiPageDraft, state["pages"]),
                                            _load(WikiIdentity, state["identities"]))
                artifact = WikiBuildArtifact(
                    scope=scope, revision=state["revision"], input_hash=input_hash,
                    generator_model=self.service.extractor.client.model,
                    prompt_version=_combined_prompt_version(),
                    documents=[WikiBuildDocument(document_id=item.document_id,
                                                 document_version_id=item.document_version_id,
                                                 content_sha256=item.content_sha256) for item in documents],
                    candidates=candidates, identities=_load(WikiIdentity, state["identities"]),
                    folders=_load(WikiFolder, state["folders"]), pages=pages,
                    claim_audits=_load(WikiClaimAuditRecord, state["audits"]),
                    claim_repairs=_load(WikiClaimRepairRecord, state["repairs"]),
                    issues=_load(WikiIssue, state["issues"]),
                )
                sources = build_source_catalog(documents, [item for item in candidates
                                                       if item.status == CandidateStatus.EVIDENCE_BOUND])
                if lease_lost.is_set():
                    raise RuntimeError("Wiki job lease was lost before finalization")
                self.repository.save_artifact(artifact, sources, lease_guard=guard)
                if self.vector_indexer is not None:
                    self.vector_indexer.index_revision(
                        **_context(scope), revision=state["revision"],
                    )
                state["failed_pages"] = sum(page.status != RevisionStatus.REVIEWING
                                            for page in _load(WikiPageDraft, state["pages"]))
            elif stage == WikiJobStage.PUBLISH:
                intent = state.get("intent", "PUBLISH" if self.service.config.publish else "PREVIEW")
                if intent == "PUBLISH" and not self.service.config.publish:
                    raise RuntimeError("Wiki publication is disabled")
                if intent == "PUBLISH" and not state["failed_pages"]:
                    if lease_lost.is_set():
                        raise RuntimeError("Wiki job lease was lost before publication")
                    self.repository.publish_revision(
                        revision=state["revision"], lease_guard=guard, **_context(scope),
                    )
                    state["published"] = True
                if state.get("finalize_generation"):
                    self.repository.complete_wiki_finalize(
                        **_context(scope), generation=state["finalize_generation"],
                    )
            self.repository.advance_wiki_job(job_id, worker_id=self.worker_id,
                                             next_stage=next_wiki_stage(stage), payload=state,
                                             attempt=lease["attempt"])
            return True
        except Exception as exc:
            backoff = min(3600, 2 ** min(lease["attempt"], 10))
            self.repository.fail_wiki_job(job_id, worker_id=self.worker_id,
                                          error=f"{type(exc).__name__}: {exc}",
                                          retry_at=int(time.time()) + backoff)
            raise
        finally:
            stop_heartbeat.set()
            thread.join(timeout=1)


def _dump(values: list[Any]) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in values]


def _load(model: type, values: list[dict[str, Any]]) -> list[Any]:
    return [model.model_validate(item) for item in values]
