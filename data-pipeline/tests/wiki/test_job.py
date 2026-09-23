from __future__ import annotations

import hashlib

import pytest

from pipeline.wiki.domain import (
    WikiKnowledgeChunk, WikiKnowledgeSpan, WikiScope, WikiSourceChunk, WikiSourceDocument,
)
from pipeline.wiki.extraction import CandidateExtractor, CandidatePromotionSelector
from pipeline.wiki.identity import IdentityResolver
from pipeline.wiki.job import WikiBuildConfig, WikiBuildService, _cached_page_matches_audit
from pipeline.wiki.page import WikiPageCompiler
from pipeline.wiki.quality import WikiQualityGate
from pipeline.wiki.taxonomy import TaxonomyPlanner
from pipeline.wiki.worker import WikiStageWorker
from pipeline.wiki.search import BgeM3WikiVectorSearch, SQLiteFTSWikiSearch, WikiSearchBackend
from storage.wiki_store import WikiStore
from tool_layer.wiki_tool import (
    WikiReadPageTool, WikiReadSourcesTool, WikiSearchEvidenceTool, WikiSearchTool,
)


def _document(number: int) -> WikiSourceDocument:
    text = f"Document {number} explains RAG as retrieval augmented generation."
    chunk = WikiSourceChunk(
        evidence_id=f"ev-{number}", section_id=f"sec-{number}", text=text,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(), ordinal=0,
    )
    knowledge = WikiKnowledgeChunk(
        id=f"kc-{number}", section_id=f"sec-{number}", text=text,
        source_spans=(WikiKnowledgeSpan(
            evidence_id=f"ev-{number}", evidence_start=0, evidence_end=len(text),
            knowledge_start=0, knowledge_end=len(text),
        ),), ordinal=0,
    )
    return WikiSourceDocument(
        scope=WikiScope(source_scope="enterprise", knowledge_base_id="kb"),
        document_id=f"doc-{number}", document_version_id=f"ver-{number}",
        title=f"Document {number}", content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        chunks=(chunk,), knowledge_chunks=(knowledge,),
    )


class FakeLLM:
    model = "fake"

    def __init__(self):
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs["schema_name"])
        name = kwargs["schema_name"]
        if name == "wiki_candidate_extraction":
            return {"candidates": [{
                "local_id": "rag", "kind": "CONCEPT", "name": "RAG", "category": None,
                "aliases": ["Retrieval Augmented Generation"], "description": "Retrieval grounded generation",
            }]}
        if name == "wiki_candidate_evidence_binding":
            candidate = kwargs["user"]["candidates"][0]
            evidence = kwargs["user"]["evidence"][0]
            return {"bindings": [{
                "candidate_handle": candidate["candidate_handle"],
                "substantive": True,
                "reason": "explained",
                "evidence_handles": [evidence["evidence_handle"]],
            }]}
        if name == "wiki_candidate_promotion":
            return {"decisions": [{
                "candidate_id": item["candidate_id"], "promote": True,
                "reason": "substantive reusable concept",
            } for item in kwargs["user"]["candidates"]]}
        if name == "wiki_taxonomy_planning":
            return {"placements": [{"identity_id": item["identity_id"], "path": ["Methods"]}
                                    for item in kwargs["user"]["identities"]]}
        if name == "wiki_page_claim_map":
            source = kwargs["user"]["sources"][0]
            return {"claims": [{
                "heading": "Overview", "text": "The source explains RAG.",
                "source_handles": [source["source_handle"]],
            }]}
        if name == "wiki_page_claim_reduce":
            claim = kwargs["user"]["atomic_claims"][0]
            return {"summary": "Grounded summary", "sections": [{
                "heading": "Overview", "claims": [{
                    "text": claim["text"], "source_handles": claim["source_handles"],
                }],
            }]}
        if name == "wiki_claim_audit":
            return {"claims": [{
                "claim_id": item["claim_id"], "verdict": "SUPPORTED", "reason_code": "ENTAILED",
                "reason": "entailed", "source_handles": [item["sources"][0]["source_handle"]],
            } for item in kwargs["user"]["claims"]]}
        if name == "wiki_identity_resolution":
            raise AssertionError("exact same-name candidates should merge without a model call")
        raise AssertionError(name)


class FakeRepository:
    def __init__(self):
        self.artifact = None
        self.sources = None
        self.published_hash = ""

    def reusable_revision(self, **kwargs):
        return self.artifact.revision if self.published_hash == kwargs["input_hash"] else None

    def load_published_candidates(self, *args, **kwargs):
        return None

    def load_published_identities(self, **kwargs):
        return []

    def load_published_taxonomy(self, **kwargs):
        return [], []

    def load_published_page_cache(self, **kwargs):
        return {}

    def load_published_page_audit_cache(self, **kwargs):
        return {}

    def save_artifact(self, artifact, source_catalog):
        self.artifact = artifact
        self.sources = source_catalog

    def publish_revision(self, **kwargs):
        self.published_hash = self.artifact.input_hash


def _service(repository, client, *, enabled=True, publish=True):
    return WikiBuildService(
        repository=repository,
        extractor=CandidateExtractor(client),
        promotion_selector=CandidatePromotionSelector(client),
        identity_resolver=IdentityResolver(client),
        taxonomy_planner=TaxonomyPlanner(client),
        page_compiler=WikiPageCompiler(client),
        quality_gate=WikiQualityGate(client, client),
        config=WikiBuildConfig(enabled=enabled, publish=publish),
    )


def test_full_build_publishes_only_reviewed_pages_and_exact_rerun_uses_zero_calls() -> None:
    repository, client = FakeRepository(), FakeLLM()
    service = _service(repository, client)
    first = service.run([_document(1), _document(2)])
    assert first.published and first.failed_pages == 0
    assert first.identities == 1 and first.pages == 4
    summaries = [page for page in repository.artifact.pages if page.page_type.value == "SUMMARY"]
    assert all(page.links for page in summaries)
    assert all("/wiki/" in page.sections[0].claims[0].rendered_text for page in summaries)
    page = summaries[0]
    trace = {"audits": [audit.model_dump(mode="json") for audit in repository.artifact.claim_audits]}
    assert _cached_page_matches_audit(page, trace)
    altered = page.model_copy(deep=True)
    altered.sections[0].claims[0].text += " Unreviewed addition."
    assert not _cached_page_matches_audit(altered, trace)
    calls = len(client.calls)
    second = service.run([_document(1), _document(2)])
    assert second.reused and second.published
    assert len(client.calls) == calls


def test_ingest_feature_flag_is_off_by_default() -> None:
    with pytest.raises(RuntimeError, match="WIKI_INGEST_ENABLED"):
        _service(FakeRepository(), FakeLLM(), enabled=False).run([_document(1)])


def test_stage_worker_resumes_and_document_deletion_rebuilds_published_scope(tmp_path) -> None:
    store, client = WikiStore(tmp_path / "wiki.sqlite3"), FakeLLM()
    service = _service(store, client)
    active = [_document(1), _document(2)]
    load = lambda lease: list(active)
    class FakeEncoder:
        model_id = "BAAI/bge-m3"

        def embed(self, texts):
            return [[1.0] + [0.0] * 1023 for _ in texts]

    vector = BgeM3WikiVectorSearch(store, FakeEncoder())
    worker = WikiStageWorker(service, load, worker_id="worker-a", vector_indexer=vector)
    def enqueue(document_id, version, digest, *, operation="UPSERT"):
        store.upsert_pending_wiki_op(
            source_scope="enterprise", owner_id="", knowledge_base_id="kb",
            document_id=document_id, document_version_id=version, content_sha256=digest,
            operation=operation,
        )
        return store.schedule_pending_wiki_jobs(intent="PUBLISH")[0]

    first = enqueue("doc-1", "ver-1", active[0].content_sha256)
    assert worker.run_once()
    with store.connection() as db:
        assert db.execute("SELECT stage FROM wiki_jobs WHERE job_id=?", (first,)).fetchone()[0] == "CITE"
    worker = WikiStageWorker(service, load, worker_id="worker-b", vector_indexer=vector)
    for _ in range(7):
        assert worker.run_once()
    assert store.search_pages("RAG", source_scope="enterprise", owner_id="",
                              knowledge_base_id="kb")
    context = {"source_scope": "enterprise", "owner_id": "", "knowledge_base_id": "kb"}
    assert len(vector.search("RAG", top_k=10, **context)) == 4
    result = WikiSearchBackend(SQLiteFTSWikiSearch(store), vector).search("RAG", **context)
    assert result and all(item["citation_authority"] is False for item in result)
    search_tool = WikiSearchTool(
        store, enterprise_knowledge_base_id="kb",
        search_backend=WikiSearchBackend(SQLiteFTSWikiSearch(store), vector),
    )
    navigated = search_tool.execute(query="RAG")["pages"]
    chosen = next(item for item in navigated if store.read_sources(item["page_id"], **context))
    assert WikiReadPageTool(store, enterprise_knowledge_base_id="kb").execute(
        page_ref=chosen["page_id"],
    )["citation_authority"] is False
    original = WikiReadSourcesTool(store, enterprise_knowledge_base_id="kb").execute(
        page_id=chosen["page_id"],
    )["sources"]
    assert original and original[0]["evidence_id"]

    class EvidenceSearch:
        def search(self, **kwargs):
            return [{"doc_id": kwargs["filters"]["doc_ids"][0],
                    "chunk_id": "ev-1", "chunk_index": 0,
                    "chunk_text": "Authoritative Evidence", "score": 0.9,
                    "version_id": original[0]["document_version_id"]}]

    evidence = WikiSearchEvidenceTool(
        store, EvidenceSearch(), enterprise_knowledge_base_id="kb",
    ).execute(query="RAG", page_id=chosen["page_id"])
    assert evidence["citation_authority"] is True and evidence["items"]

    active.pop()
    second = enqueue("doc-2", "ver-deleted-2", "0" * 64, operation="DELETE")
    for _ in range(8):
        assert worker.run_once()
    with store.connection() as db:
        assert db.execute("SELECT status FROM wiki_jobs WHERE job_id=?", (second,)).fetchone()[0] == "COMPLETE"
        assert db.execute("SELECT status FROM wiki_finalize_requests").fetchone()[0] == "COMPLETE"
    pages = store.search_pages("RAG", source_scope="enterprise", owner_id="",
                               knowledge_base_id="kb")
    assert pages
    assert {item["page_id"] for item in vector.search("RAG", top_k=10, **context)} == {
        item["page_id"] for item in store.active_vector_pages(**context)[1]
    }
    assert all("ver-2" not in store.read_page(page["page_id"], source_scope="enterprise",
                                                 owner_id="", knowledge_base_id="kb")["document_version_ids"]
               for page in pages)

    active.clear()
    enqueue("doc-1", "ver-deleted-1", "0" * 64, operation="DELETE")
    for _ in range(8):
        assert worker.run_once()
    assert store.search_pages("RAG", source_scope="enterprise", owner_id="",
                              knowledge_base_id="kb") == []
    assert vector.search("RAG", top_k=10, **context) == []
