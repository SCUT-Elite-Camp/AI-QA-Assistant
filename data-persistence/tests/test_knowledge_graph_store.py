from __future__ import annotations

import pytest

from shared_runtime.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeNode,
    KnowledgeSource,
    stable_knowledge_edge_id,
    stable_knowledge_node_id,
)
from storage.knowledge_graph_store import KnowledgeGraphStore


def _graph(scope: str, owner: str, kb: str):
    document = stable_knowledge_node_id(
        source_scope=scope, owner_id=owner, knowledge_base_id=kb,
        node_type="document", canonical_name="Agent Architecture",
    )
    concept = stable_knowledge_node_id(
        source_scope=scope, owner_id=owner, knowledge_base_id=kb,
        node_type="concept", canonical_name="Tool Routing",
    )
    edge = stable_knowledge_edge_id(document, "discusses", concept)
    nodes = [
        KnowledgeNode(id=document, node_type="document", canonical_name="Agent Architecture"),
        KnowledgeNode(id=concept, node_type="concept", canonical_name="Tool Routing", aliases=["工具路由"]),
    ]
    edges = [KnowledgeEdge(
        id=edge, source_node_id=document, target_node_id=concept,
        relation_type="discusses",
    )]
    sources = [
        KnowledgeSource(
            target_kind="node", target_id=document, document_version_id="ver-1",
            evidence_id="ev-1", section_id="sec-agent",
        ),
        KnowledgeSource(
            target_kind="node", target_id=concept, document_version_id="ver-1",
            evidence_id="ev-2", section_id="sec-tools",
        ),
        KnowledgeSource(
            target_kind="edge", target_id=edge, document_version_id="ver-1",
            evidence_id="ev-2", section_id="sec-tools",
        ),
    ]
    return nodes, edges, sources


def test_active_revision_search_returns_navigation_priors_not_evidence(tmp_path) -> None:
    store = KnowledgeGraphStore(tmp_path / "graph.sqlite3")
    nodes, edges, sources = _graph("enterprise", "", "kb-1")
    store.replace_revision(
        source_scope="enterprise", owner_id="", knowledge_base_id="kb-1",
        revision="r1", input_hash="hash-1", nodes=nodes, edges=edges, sources=sources,
    )

    hits = store.search(
        "工具路由", source_scope="enterprise", owner_id="",
        knowledge_base_id="kb-1",
    )

    assert hits[0]["canonical_name"] == "Tool Routing"
    assert hits[0]["citation_authority"] is False
    assert hits[0]["evidence_ids"] == ["ev-2"]
    assert hits[0]["section_ids"] == ["sec-tools"]


def test_personal_graph_is_owner_isolated(tmp_path) -> None:
    store = KnowledgeGraphStore(tmp_path / "graph.sqlite3")
    nodes, edges, sources = _graph("personal", "alice", "kb-1")
    store.replace_revision(
        source_scope="personal", owner_id="alice", knowledge_base_id="kb-1",
        revision="r1", input_hash="hash-1", nodes=nodes, edges=edges, sources=sources,
    )

    assert store.search(
        "Tool", source_scope="personal", owner_id="bob", knowledge_base_id="kb-1",
    ) == []
    with pytest.raises(ValueError, match="requires owner_id"):
        store.search(
            "Tool", source_scope="personal", owner_id="", knowledge_base_id="kb-1",
        )


def test_revision_without_complete_evidence_provenance_is_rejected(tmp_path) -> None:
    store = KnowledgeGraphStore(tmp_path / "graph.sqlite3")
    nodes, edges, sources = _graph("enterprise", "", "kb-1")

    with pytest.raises(ValueError, match="requires Evidence provenance"):
        store.replace_revision(
            source_scope="enterprise", owner_id="", knowledge_base_id="kb-1",
            revision="r1", input_hash="hash-1", nodes=nodes, edges=edges,
            sources=sources[:-1],
        )


def test_invalidated_document_stales_active_revision(tmp_path) -> None:
    store = KnowledgeGraphStore(tmp_path / "graph.sqlite3")
    nodes, edges, sources = _graph("enterprise", "", "kb-1")
    store.replace_revision(
        source_scope="enterprise", owner_id="", knowledge_base_id="kb-1",
        revision="r1", input_hash="hash-1", nodes=nodes, edges=edges, sources=sources,
    )

    assert store.mark_stale_for_document_version("ver-1") == 1
    assert store.search(
        "Tool", source_scope="enterprise", owner_id="", knowledge_base_id="kb-1",
    ) == []
