from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class KnowledgeNodeType(StrEnum):
    PROJECT = "project"
    MODULE = "module"
    DOCUMENT_TYPE = "document_type"
    DOCUMENT = "document"
    SECTION = "section"
    COMPONENT = "component"
    TECHNOLOGY = "technology"
    FEATURE = "feature"
    PERSON = "person"
    CONCEPT = "concept"
    ENTITY = "entity"
    EVENT = "event"
    SPRINT = "sprint"
    TASK = "task"
    DECISION = "decision"
    DELIVERABLE = "deliverable"


class KnowledgeRelationType(StrEnum):
    CONTAINS = "contains"
    BELONGS_TO = "belongs_to"
    RELATED_TO = "related_to"
    DEPENDS_ON = "depends_on"
    IMPLEMENTS = "implements"
    DISCUSSES = "discusses"
    RECORDS = "records"
    ASSIGNED_TO = "assigned_to"
    PARTICIPATES_IN = "participates_in"
    PRODUCES = "produces"
    DECIDES = "decides"
    SUPERSEDES = "supersedes"


class KnowledgeNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    node_type: KnowledgeNodeType
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "canonical_name")
    @classmethod
    def nonempty(cls, value: str) -> str:
        value = " ".join(value.split()).strip()
        if not value:
            raise ValueError("knowledge node identity must not be empty")
        return value


class KnowledgeEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_node_id: str
    target_node_id: str
    relation_type: KnowledgeRelationType
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def no_self_loop(self) -> "KnowledgeEdge":
        if self.source_node_id == self.target_node_id:
            raise ValueError("knowledge graph self loops are not allowed")
        return self


class KnowledgeSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_kind: Literal["node", "edge"]
    target_id: str
    document_version_id: str
    evidence_id: str
    section_id: str = ""
    support_span: dict[str, Any] = Field(default_factory=dict)

    @field_validator("target_id", "document_version_id", "evidence_id")
    @classmethod
    def require_source_identity(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("knowledge source identity must not be empty")
        return value


def stable_knowledge_node_id(
    *,
    source_scope: str,
    knowledge_base_id: str,
    owner_id: str,
    node_type: str,
    canonical_name: str,
    identity_key: str = "",
) -> str:
    values = (
        source_scope.casefold().strip(), knowledge_base_id.strip(), owner_id.strip(),
        node_type.casefold().strip(),
        " ".join((identity_key or canonical_name).casefold().split()),
    )
    if not values[0] or not values[1] or not values[3] or not values[4]:
        raise ValueError("knowledge node identity fields must be non-empty")
    if values[0] == "personal" and not values[2]:
        raise ValueError("personal knowledge nodes require owner_id")
    return "kgn_" + hashlib.sha256(":".join(values).encode("utf-8")).hexdigest()[:24]


def stable_knowledge_edge_id(
    source_node_id: str,
    relation_type: str,
    target_node_id: str,
) -> str:
    if not source_node_id or not relation_type or not target_node_id:
        raise ValueError("knowledge edge identity fields must be non-empty")
    value = f"{source_node_id}:{relation_type.casefold()}:{target_node_id}"
    return "kge_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
