from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Protocol, TypeAlias

from models.document import Document
from shared_runtime.knowledge_graph import (
    KnowledgeEdge, KnowledgeNode, KnowledgeNodeType, KnowledgeRelationType,
    KnowledgeSource, stable_knowledge_edge_id, stable_knowledge_node_id,
)


@dataclass(frozen=True)
class KnowledgeAssertion:
    """Legacy document-to-entity assertion retained for compatibility."""
    document_version_id: str
    evidence_id: str
    section_id: str
    node_type: KnowledgeNodeType
    canonical_name: str
    aliases: tuple[str, ...] = ()
    description: str = ""
    relation_to_document: KnowledgeRelationType = KnowledgeRelationType.DISCUSSES


@dataclass(frozen=True)
class KnowledgeEndpoint:
    node_type: KnowledgeNodeType
    canonical_name: str
    aliases: tuple[str, ...] = ()
    description: str = ""
    attributes: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class KnowledgeTripleAssertion:
    """A semantic edge grounded in one exact Evidence substring."""
    document_version_id: str
    evidence_id: str
    section_id: str
    subject: KnowledgeEndpoint
    relation: KnowledgeRelationType
    object: KnowledgeEndpoint
    support_quote: str
    quote_start: int
    quote_end: int


GraphAssertion: TypeAlias = KnowledgeAssertion | KnowledgeTripleAssertion


class KnowledgeExtractionProvider(Protocol):
    def extract(self, document: Document) -> list[GraphAssertion]: ...


@dataclass(frozen=True)
class CompiledKnowledgeGraph:
    nodes: list[KnowledgeNode]
    edges: list[KnowledgeEdge]
    sources: list[KnowledgeSource]
    input_hash: str


_WORK_TYPES = {
    KnowledgeNodeType.EVENT, KnowledgeNodeType.SPRINT, KnowledgeNodeType.TASK,
    KnowledgeNodeType.DECISION, KnowledgeNodeType.DELIVERABLE,
}


def resolve_assertions(assertions: list[GraphAssertion]) -> list[GraphAssertion]:
    """Conservatively align exact canonical names and aliases within each type."""
    triples = sorted(
        (item for item in assertions if isinstance(item, KnowledgeTripleAssertion)),
        key=lambda item: (
            KnowledgeNodeType(item.subject.node_type).value, item.subject.canonical_name.casefold(),
            KnowledgeRelationType(item.relation).value, KnowledgeNodeType(item.object.node_type).value,
            item.object.canonical_name.casefold(), item.document_version_id,
            item.evidence_id, item.quote_start,
        ),
    )
    legacy = sorted(
        (item for item in assertions if isinstance(item, KnowledgeAssertion)),
        key=lambda item: (
            KnowledgeNodeType(item.node_type).value, item.canonical_name.casefold(),
            item.document_version_id, item.evidence_id,
        ),
    )
    representatives: dict[tuple[KnowledgeNodeType, str], KnowledgeEndpoint] = {}

    def norm(value: str) -> str:
        return " ".join(value.casefold().split())

    for assertion in triples:
        for endpoint in (assertion.subject, assertion.object):
            keys = [
                (endpoint.node_type, norm(name))
                for name in (endpoint.canonical_name, *endpoint.aliases) if norm(name)
            ]
            matches = [representatives[key] for key in keys if key in representatives]
            merged = matches[0] if matches else endpoint
            aliases = tuple(dict.fromkeys([
                *merged.aliases, *endpoint.aliases,
                *(() if merged.canonical_name == endpoint.canonical_name else (endpoint.canonical_name,)),
            ]))
            merged = replace(
                merged, aliases=aliases,
                description=merged.description or endpoint.description,
                attributes=tuple(dict.fromkeys([*merged.attributes, *endpoint.attributes])),
            )
            for key in keys:
                representatives[key] = merged

    resolved: list[GraphAssertion] = [*legacy]
    for assertion in triples:
        subject = representatives.get(
            (assertion.subject.node_type, norm(assertion.subject.canonical_name)), assertion.subject,
        )
        object_ = representatives.get(
            (assertion.object.node_type, norm(assertion.object.canonical_name)), assertion.object,
        )
        if subject.node_type == object_.node_type and norm(subject.canonical_name) == norm(object_.canonical_name):
            continue
        resolved.append(replace(assertion, subject=subject, object=object_))
    return resolved


def compile_knowledge_graph(
    documents: list[Document], *, source_scope: str, owner_id: str,
    knowledge_base_id: str, assertions: list[GraphAssertion] | None = None,
) -> CompiledKnowledgeGraph:
    """Compile an Evidence-authorized navigation graph; it is not citation authority."""
    context = dict(source_scope=source_scope, owner_id=owner_id, knowledge_base_id=knowledge_base_id)
    nodes: dict[str, KnowledgeNode] = {}
    edges: dict[str, KnowledgeEdge] = {}
    sources: dict[tuple[str, str, str, str, str], KnowledgeSource] = {}
    documents_by_version: dict[str, str] = {}
    documents_by_page: dict[str, tuple[str, str, str]] = {}

    def node(node_type: KnowledgeNodeType, name: str, *, aliases=(), description="",
             identity_key="", metadata: dict | None = None) -> str:
        identifier = stable_knowledge_node_id(
            **context, node_type=node_type.value, canonical_name=name, identity_key=identity_key,
        )
        current = nodes.get(identifier)
        nodes[identifier] = KnowledgeNode(
            id=identifier, node_type=node_type, canonical_name=name,
            aliases=list(dict.fromkeys([
                *(current.aliases if current else []),
                *(str(value).strip() for value in aliases if str(value).strip()),
            ])),
            description=description or (current.description if current else ""),
            metadata={**(current.metadata if current else {}), **(metadata or {})},
        )
        return identifier

    def source(target_kind: str, target_id: str, version_id: str, evidence_id: str,
               section_id="", support_span: dict | None = None) -> None:
        item = KnowledgeSource(
            target_kind=target_kind, target_id=target_id,
            document_version_id=version_id, evidence_id=evidence_id,
            section_id=section_id, support_span=support_span or {},
        )
        sources[(target_kind, target_id, version_id, evidence_id, section_id)] = item

    def edge(source_id: str, relation: KnowledgeRelationType, target_id: str, *,
             version_id: str, evidence_id: str, section_id="",
             support_span: dict | None = None) -> str:
        identifier = stable_knowledge_edge_id(source_id, relation.value, target_id)
        edges[identifier] = KnowledgeEdge(
            id=identifier, source_node_id=source_id, target_node_id=target_id,
            relation_type=relation,
        )
        source("edge", identifier, version_id, evidence_id, section_id, support_span)
        return identifier

    # L0: source-stable documents and Evidence-backed sections.
    for document in documents:
        version_id = str(document.version_id or "")
        evidence_ids = [chunk.chunk_id for chunk in document.chunks if chunk.chunk_id]
        if not version_id or not evidence_ids:
            continue
        anchor = evidence_ids[0]
        page_id = str(document.metadata.get("page_id") or document.doc_id)
        document_id = node(
            KnowledgeNodeType.DOCUMENT, document.title,
            identity_key=f"document:{page_id}",
            aliases=document.metadata.get("aliases") or (),
            description=str(document.metadata.get("description") or ""),
            metadata={"page_id": page_id, "version": str(document.metadata.get("version") or ""),
                      "source_url": document.source_url},
        )
        documents_by_version[version_id] = document_id
        documents_by_page[page_id] = (document_id, version_id, anchor)
        source("node", document_id, version_id, anchor)

        doc_type_name = str(document.metadata.get("document_type") or document.doc_type or "document")
        type_id = node(KnowledgeNodeType.DOCUMENT_TYPE, doc_type_name)
        source("node", type_id, version_id, anchor)
        edge(type_id, KnowledgeRelationType.CONTAINS, document_id,
             version_id=version_id, evidence_id=anchor)

        hierarchy_parent = ""
        for index, value in enumerate(document.metadata.get("ancestor_path") or []):
            name = str(value.get("title") if isinstance(value, dict) else value).strip()
            if not name:
                continue
            source_id = str(value.get("id") if isinstance(value, dict) else "").strip()
            hierarchy_id = node(
                KnowledgeNodeType.PROJECT if index == 0 else KnowledgeNodeType.MODULE,
                name, identity_key=(
                    f"project:{source_id}" if index == 0 and source_id
                    else f"module:{source_id}" if source_id else ""
                ),
            )
            source("node", hierarchy_id, version_id, anchor)
            if hierarchy_parent:
                edge(hierarchy_parent, KnowledgeRelationType.CONTAINS, hierarchy_id,
                     version_id=version_id, evidence_id=anchor)
            hierarchy_parent = hierarchy_id
        if hierarchy_parent:
            edge(hierarchy_parent, KnowledgeRelationType.CONTAINS, document_id,
                 version_id=version_id, evidence_id=anchor)

        for section in document.sections:
            section_evidence = next((value for value in section.evidence_ids if value in evidence_ids), "")
            if not section_evidence:
                continue
            graph_section_id = node(
                KnowledgeNodeType.SECTION, section.title,
                identity_key=f"section:{version_id}:{section.id}",
                metadata={"section_id": section.id, "section_path": section.section_path},
            )
            source("node", graph_section_id, version_id, section_evidence, section.id)
            edge(document_id, KnowledgeRelationType.CONTAINS, graph_section_id,
                 version_id=version_id, evidence_id=section_evidence, section_id=section.id)

    # Real Confluence parent-page relations; child pages remain separate Documents.
    for document in documents:
        child = documents_by_version.get(str(document.version_id or ""))
        parent = documents_by_page.get(str(document.metadata.get("parent_id") or ""))
        if child and parent:
            anchor = next(chunk.chunk_id for chunk in document.chunks if chunk.chunk_id)
            edge(parent[0], KnowledgeRelationType.CONTAINS, child,
                 version_id=str(document.version_id), evidence_id=anchor)

    # L1/L2: exact Evidence-bound semantic triples and document navigation priors.
    for assertion in resolve_assertions(assertions or []):
        document_id = documents_by_version.get(assertion.document_version_id)
        if not document_id or not assertion.evidence_id:
            continue
        if isinstance(assertion, KnowledgeAssertion):
            semantic_id = node(KnowledgeNodeType(assertion.node_type), assertion.canonical_name,
                               aliases=assertion.aliases, description=assertion.description)
            source("node", semantic_id, assertion.document_version_id,
                   assertion.evidence_id, assertion.section_id)
            edge(document_id, KnowledgeRelationType(assertion.relation_to_document), semantic_id,
                 version_id=assertion.document_version_id, evidence_id=assertion.evidence_id,
                 section_id=assertion.section_id)
            continue

        span = {"quote": assertion.support_quote, "start": assertion.quote_start,
                "end": assertion.quote_end}
        subject_id = node(KnowledgeNodeType(assertion.subject.node_type),
                          assertion.subject.canonical_name, aliases=assertion.subject.aliases,
                          description=assertion.subject.description,
                          metadata=dict(assertion.subject.attributes))
        object_id = node(KnowledgeNodeType(assertion.object.node_type),
                         assertion.object.canonical_name, aliases=assertion.object.aliases,
                         description=assertion.object.description,
                         metadata=dict(assertion.object.attributes))
        for semantic_id in (subject_id, object_id):
            source("node", semantic_id, assertion.document_version_id,
                   assertion.evidence_id, assertion.section_id, span)
        edge(subject_id, KnowledgeRelationType(assertion.relation), object_id,
             version_id=assertion.document_version_id, evidence_id=assertion.evidence_id,
             section_id=assertion.section_id, support_span=span)
        for endpoint, semantic_id in ((assertion.subject, subject_id), (assertion.object, object_id)):
            relation = (KnowledgeRelationType.RECORDS
                        if KnowledgeNodeType(endpoint.node_type) in _WORK_TYPES
                        else KnowledgeRelationType.DISCUSSES)
            edge(document_id, relation, semantic_id,
                 version_id=assertion.document_version_id, evidence_id=assertion.evidence_id,
                 section_id=assertion.section_id, support_span=span)

    canonical = {
        "nodes": [item.model_dump(mode="json") for item in sorted(nodes.values(), key=lambda value: value.id)],
        "edges": [item.model_dump(mode="json") for item in sorted(edges.values(), key=lambda value: value.id)],
        "sources": [item.model_dump(mode="json") for item in sorted(
            sources.values(), key=lambda value: (value.target_kind, value.target_id,
                                                  value.document_version_id, value.evidence_id,
                                                  value.section_id))],
    }
    input_hash = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return CompiledKnowledgeGraph(
        nodes=list(nodes.values()), edges=list(edges.values()),
        sources=list(sources.values()), input_hash=input_hash,
    )
