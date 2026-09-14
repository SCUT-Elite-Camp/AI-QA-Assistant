from __future__ import annotations

from typing import Any, Protocol

from models.document import Document

from .knowledge_graph import (
    GraphAssertion, KnowledgeExtractionProvider, compile_knowledge_graph,
)


class RevisionStore(Protocol):
    def replace_revision(self, **kwargs: Any) -> None: ...


def build_and_activate_knowledge_graph(
    documents: list[Document],
    *,
    provider: KnowledgeExtractionProvider,
    store: RevisionStore,
    source_scope: str,
    owner_id: str,
    knowledge_base_id: str,
    revision: str,
    generator_model: str,
    prompt_version: str,
) -> dict[str, Any]:
    """Extract a graph offline; failed extraction never activates a partial revision."""
    assertions: list[GraphAssertion] = []
    failures: list[dict[str, str]] = []
    for document in documents:
        try:
            assertions.extend(provider.extract(document))
        except Exception as exc:
            failures.append({
                "document_version_id": document.version_id,
                "error": exc.__class__.__name__,
            })
    return activate_knowledge_revision(
        documents,
        assertions=assertions,
        failures=failures,
        store=store,
        source_scope=source_scope,
        owner_id=owner_id,
        knowledge_base_id=knowledge_base_id,
        revision=revision,
        generator_model=generator_model,
        prompt_version=prompt_version,
    )


def activate_knowledge_revision(
    documents: list[Document],
    *,
    assertions: list[GraphAssertion],
    failures: list[dict[str, str]],
    store: RevisionStore,
    source_scope: str,
    owner_id: str,
    knowledge_base_id: str,
    revision: str,
    generator_model: str,
    prompt_version: str,
    expected_documents: int | None = None,
) -> dict[str, Any]:
    """Single compile-and-activate boundary for online jobs and offline batches.

    The caller owns extraction, caching, and audit policy. This function owns
    graph compilation and the all-or-nothing revision store write.
    """
    graph = compile_knowledge_graph(
        documents, source_scope=source_scope, owner_id=owner_id,
        knowledge_base_id=knowledge_base_id, assertions=assertions,
    )
    complete = bool(documents) and not failures and (
        expected_documents is None or len(documents) == expected_documents
    )
    if complete:
        store.replace_revision(
            source_scope=source_scope,
            owner_id=owner_id,
            knowledge_base_id=knowledge_base_id,
            revision=revision,
            input_hash=graph.input_hash,
            nodes=graph.nodes,
            edges=graph.edges,
            sources=graph.sources,
            generator_model=generator_model,
            prompt_version=prompt_version,
        )
    return {
        "status": "PASS" if complete else "FAILED",
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "sources": len(graph.sources),
        "assertions": len(assertions),
        "failures": failures,
        "input_hash": graph.input_hash,
        "activated": complete,
    }
