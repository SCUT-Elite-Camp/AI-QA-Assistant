from __future__ import annotations

from models.document import Chunk, Document
from pipeline.knowledge_graph import (
    KnowledgeAssertion, KnowledgeEndpoint, KnowledgeTripleAssertion,
    compile_knowledge_graph,
)


def _document() -> Document:
    return Document(
        doc_id="doc-1",
        title="Agent Architecture",
        content="Agent plans work and routes tools.",
        space="RAG",
        address="C:/export/project/agent.md",
        last_updated="",
        doc_type="md",
        version_id="ver-1",
        metadata={"ancestor_path": ["RAG Project", "Architecture"]},
        chunks=[Chunk(
            index=0, chunk_id="ev-1", text="Agent plans work and routes tools.",
            section_path=["Agent Layer"],
        )],
    )


def test_compiler_builds_hierarchy_and_evidence_bound_semantic_nodes() -> None:
    graph = compile_knowledge_graph(
        [_document()],
        source_scope="enterprise",
        owner_id="",
        knowledge_base_id="kb-1",
        assertions=[KnowledgeAssertion(
            document_version_id="ver-1",
            evidence_id="ev-1",
            section_id="sec-agent",
            node_type="concept",
            canonical_name="Tool Routing",
            aliases=("工具路由",),
            description="Routes model actions to allowlisted tools.",
        )],
    )

    assert {node.node_type.value for node in graph.nodes} >= {
        "project", "module", "document_type", "document", "concept",
    }
    assert {edge.relation_type.value for edge in graph.edges} >= {"contains", "discusses"}
    assert {(source.target_kind, source.target_id) for source in graph.sources} == {
        *(('node', node.id) for node in graph.nodes),
        *(('edge', edge.id) for edge in graph.edges),
    }
    assert len(graph.input_hash) == 64


def test_compiler_is_path_independent_and_deterministic() -> None:
    first = compile_knowledge_graph(
        [_document()], source_scope="enterprise", owner_id="", knowledge_base_id="kb-1",
    )
    moved = _document().model_copy(update={"address": "D:/moved/agent.md"})
    second = compile_knowledge_graph(
        [moved], source_scope="enterprise", owner_id="", knowledge_base_id="kb-1",
    )

    assert first.input_hash == second.input_hash
    assert {node.id for node in first.nodes} == {node.id for node in second.nodes}


def test_document_without_authoritative_evidence_is_not_published() -> None:
    empty = _document().model_copy(update={"chunks": []})
    graph = compile_knowledge_graph(
        [empty], source_scope="enterprise", owner_id="", knowledge_base_id="kb-1",
    )

    assert graph.nodes == []
    assert graph.edges == []
    assert graph.sources == []


def test_compiler_keeps_triple_provenance_and_work_navigation() -> None:
    assertion = KnowledgeTripleAssertion(
        document_version_id="ver-1", evidence_id="ev-1", section_id="sec-agent",
        subject=KnowledgeEndpoint(node_type="task", canonical_name="Route tool calls"),
        relation="produces",
        object=KnowledgeEndpoint(node_type="deliverable", canonical_name="Tool routing module"),
        support_quote="Agent plans work and routes tools.", quote_start=0, quote_end=34,
    )
    graph = compile_knowledge_graph(
        [_document()], source_scope="enterprise", owner_id="", knowledge_base_id="kb-1",
        assertions=[assertion],
    )

    assert {edge.relation_type.value for edge in graph.edges} >= {"produces", "records"}
    semantic_sources = [source for source in graph.sources if source.support_span]
    assert semantic_sources
    assert all(source.support_span["quote"] == assertion.support_quote for source in semantic_sources)


def test_compiler_hash_is_independent_of_assertion_completion_order() -> None:
    assertions = [
        KnowledgeAssertion(
            document_version_id="ver-1", evidence_id="ev-1", section_id="",
            node_type="concept", canonical_name=name,
        )
        for name in ("Beta", "Alpha")
    ]
    kwargs = dict(source_scope="enterprise", owner_id="", knowledge_base_id="kb-1")

    first = compile_knowledge_graph([_document()], assertions=assertions, **kwargs)
    second = compile_knowledge_graph([_document()], assertions=list(reversed(assertions)), **kwargs)

    assert first.input_hash == second.input_hash
