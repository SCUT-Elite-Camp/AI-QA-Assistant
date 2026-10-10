"""Research uses Chat's tools without weakening ACL or approved snapshots."""
import json
from unittest.mock import Mock

import pytest
from agent.schemas.research import ResearchRequest, SourceScope
from deep_research.manifest import LocalDocumentResolver
from deep_research.tools import EnterpriseResearchToolAdapter, ManifestAccessError, ToolCallContext
from toolset.tool_layer.document_tools import GetDocumentTool


@pytest.fixture
def environment(tmp_path):
    payload = {"doc_id": "shared", "title": "Shared", "version": "1", "user_id": "bob",
               "chunks": [{"chunk_id": "shared:0", "index": 0, "text": "Total commits: 9"}]}
    (tmp_path / "shared.json").write_text(json.dumps(payload), encoding="utf-8")
    resolver = LocalDocumentResolver(tmp_path)
    manifest = resolver.resolve("research-test", SourceScope(document_ids=["shared"]))
    search = Mock(documents_dir=tmp_path)
    search.search.return_value = [{"doc_id": "shared", "chunk_id": "shared:0", "chunk_index": 0,
                                   "chunk_text": "Total commits: 9", "score": 0.5}]
    policy = Mock()
    policy.accessible_doc_ids.return_value = {"shared"}
    reader = GetDocumentTool(tmp_path)
    adapter = EnterpriseResearchToolAdapter(search, reader, policy)
    context = ToolCallContext("research-test", "task", "trace", "alice", manifest, retrieval_mode="bm25")
    yield adapter, context, policy, search, tmp_path, payload
    adapter.close()


def test_shared_document_owner_is_not_a_replacement_for_live_acl(environment):
    adapter, context, _, search, _, _ = environment
    hit = adapter.search("commits", context)[0]
    assert search.search.call_args.kwargs["filters"] == {"doc_ids": ["shared"]}
    assert search.search.call_args.kwargs["mode"] == "bm25"
    assert hit.retrieval_metadata["retrieval_backend"] == "toolset.search_documents"
    assert adapter.read_document_range("shared", context, locator=hit.locator_hint).excerpt == "Total commits: 9"


def test_revocation_blocks_search_read_and_catalog(environment):
    adapter, context, policy, search, _, _ = environment
    policy.accessible_doc_ids.return_value = set()
    for callback in (lambda: adapter.search("commits", context),
                     lambda: adapter.read_document_range("shared", context),
                     lambda: adapter.list_documents(context)):
        with pytest.raises(ManifestAccessError): callback()
    search.search.assert_not_called()


def test_empty_scope_does_not_call_global_search(environment):
    adapter, context, _, search, _, _ = environment
    assert adapter.search("commits", context, source_ids=[]) == []
    search.search.assert_not_called()


def test_changed_source_is_not_used_as_frozen_evidence(environment):
    adapter, context, _, _, root, payload = environment
    payload["version"] = "2"
    (root / "shared.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ManifestAccessError, match="version_changed"):
        adapter.read_document_range("shared", context, locator="shared:0")


def test_revocation_during_search_does_not_release_results(environment):
    adapter, context, policy, _, _, _ = environment
    policy.accessible_doc_ids.side_effect = [{"shared"}, set()]
    with pytest.raises(ManifestAccessError): adapter.search("commits", context)


def test_retrieval_mode_is_validated():
    with pytest.raises(ValueError):
        ResearchRequest(query="q", source_scope=SourceScope(document_ids=["d"]), retrieval_mode="auto")


def test_live_checks_only_cover_frozen_scope_without_caching_grants(environment):
    adapter, context, policy, _, _, _ = environment
    adapter.read_document_range('shared', context, locator='shared:0')
    assert policy.accessible_doc_ids.call_args.args == ('alice', ['shared'])
    policy.accessible_doc_ids.return_value = set()
    with pytest.raises(ManifestAccessError):
        adapter.read_document_range('shared', context, locator='shared:0')


def test_short_note_read_keeps_full_context_and_exact_anchor(environment):
    adapter, context, _, _, path, payload = environment
    payload['content'] = 'Event date.\n\nObserved workflow.\n\nEvidence links need repair.'
    payload['chunks'] = [{'chunk_id': f'shared:{i}', 'index': i, 'text': text}
                         for i, text in enumerate(['Event date.', 'Observed workflow.', 'Evidence links need repair.'])]
    (path/'shared.json').write_text(json.dumps(payload))
    manifest = LocalDocumentResolver(path).resolve('research-test', SourceScope(document_ids=['shared']))
    context = ToolCallContext('research-test', 'task', 'trace', 'alice', manifest, retrieval_mode='hybrid')
    read = adapter.read_document_range('shared', context, locator='shared:0')
    assert read.anchor_excerpt == 'Event date.'
    assert 'Evidence links need repair.' in read.excerpt
    assert read.locator == 'shared:0'
