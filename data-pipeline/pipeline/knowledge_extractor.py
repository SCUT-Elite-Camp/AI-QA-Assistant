from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from models.document import Document
from shared_runtime.knowledge_graph import KnowledgeNodeType, KnowledgeRelationType

from .knowledge_graph import KnowledgeEndpoint, KnowledgeTripleAssertion


PROMPT_VERSION = "confluence-layered-kg-v3"
ONTOLOGY_VERSION = "confluence-layered-ontology-v1"

SEMANTIC_NODE_TYPES = {
    KnowledgeNodeType.COMPONENT, KnowledgeNodeType.TECHNOLOGY,
    KnowledgeNodeType.FEATURE, KnowledgeNodeType.PERSON, KnowledgeNodeType.CONCEPT,
    KnowledgeNodeType.EVENT, KnowledgeNodeType.SPRINT, KnowledgeNodeType.TASK,
    KnowledgeNodeType.DECISION, KnowledgeNodeType.DELIVERABLE,
}
SEMANTIC_RELATIONS = {
    KnowledgeRelationType.BELONGS_TO, KnowledgeRelationType.DISCUSSES,
    KnowledgeRelationType.IMPLEMENTS, KnowledgeRelationType.DEPENDS_ON,
    KnowledgeRelationType.RELATED_TO, KnowledgeRelationType.RECORDS,
    KnowledgeRelationType.ASSIGNED_TO, KnowledgeRelationType.PARTICIPATES_IN,
    KnowledgeRelationType.PRODUCES, KnowledgeRelationType.DECIDES,
    KnowledgeRelationType.SUPERSEDES,
}
_GENERIC_NAMES = {
    "agent", "architecture", "component", "concept", "decision", "deliverable",
    "entity", "event", "evidence", "feature", "layer", "meeting", "module",
    "project", "retrieval", "sprint", "style", "system", "task", "technology",
    "toolset", "work", "架构", "任务", "会议", "功能", "技术", "模块", "系统", "项目",
}
_EVENT_MARKERS = (
    "meeting", "minutes", "review", "demo", "planning", "retrospective", "launch",
    "会议", "纪要", "评审", "演示", "规划会", "复盘", "发布会",
)
_SPRINT_MARKERS = ("sprint", "迭代")


class LocalOpenAIKnowledgeExtractionProvider:
    """Strict, Evidence-bound extractor for a local OpenAI-compatible model."""

    def __init__(
        self, *, base_url: str, model: str, api_key: str = "local-knowledge-graph",
        timeout_seconds: float = 300.0, max_input_chars: int = 24000,
        allow_external: bool = False, prompt_version: str = PROMPT_VERSION,
        ontology_version: str = ONTOLOGY_VERSION,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model.strip()
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_input_chars = max(1000, int(max_input_chars))
        self.prompt_version = prompt_version.strip() or PROMPT_VERSION
        self.ontology_version = ontology_version.strip() or ONTOLOGY_VERSION
        self.request_count = 0
        if not self.model:
            raise ValueError("knowledge extraction model is required")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
            "localhost", "127.0.0.1", "::1",
        }:
            if not allow_external:
                raise ValueError("private knowledge extraction requires a local endpoint")

    def extract(self, document: Document) -> list[KnowledgeTripleAssertion]:
        allowed = {chunk.chunk_id: chunk for chunk in document.chunks if chunk.chunk_id}
        if not allowed:
            return []
        batches: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        size = 0
        for chunk in document.chunks:
            payload = {
                "evidence_id": chunk.chunk_id,
                "section_id": self._section_id(document, chunk.chunk_id),
                "section_path": chunk.section_path,
                "content": chunk.text,
            }
            encoded_size = len(json.dumps(payload, ensure_ascii=False))
            if current and size + encoded_size > self.max_input_chars:
                batches.append(current)
                current, size = [], 0
            current.append(payload)
            size += encoded_size
        if current:
            batches.append(current)

        assertions: list[KnowledgeTripleAssertion] = []
        seen: set[tuple[str, str, str, str, str]] = set()
        for batch in batches:
            for row in self._rows_with_split_retry(document.title, batch):
                assertion = self._validate_row(document, allowed, row)
                if assertion is None:
                    continue
                key = (
                    assertion.subject.node_type.value,
                    assertion.subject.canonical_name.casefold(),
                    assertion.relation.value,
                    assertion.object.node_type.value,
                    assertion.object.canonical_name.casefold(),
                )
                if key not in seen:
                    seen.add(key)
                    assertions.append(assertion)
        return assertions

    def _rows_with_split_retry(
        self, title: str, evidence: list[dict[str, Any]], max_assertions: int = 8,
    ) -> list[Any]:
        """Recover truncation by bounding output first, then reducing the failed input."""
        try:
            return list(self._chat(
                title, evidence, max_assertions=max_assertions,
            ).get("assertions") or [])
        except json.JSONDecodeError:
            if max_assertions > 2:
                return self._rows_with_split_retry(
                    title, evidence, max_assertions=max(2, max_assertions // 2),
                )
            if len(evidence) <= 1:
                raise
            middle = len(evidence) // 2
            return [
                *self._rows_with_split_retry(title, evidence[:middle], max_assertions=2),
                *self._rows_with_split_retry(title, evidence[middle:], max_assertions=2),
            ]

    def _validate_row(self, document: Document, allowed: dict[str, Any], row: Any) -> KnowledgeTripleAssertion | None:
        if not isinstance(row, dict):
            return None
        evidence_id = str(row.get("evidence_id") or "").strip()
        chunk = allowed.get(evidence_id)
        if chunk is None:
            return None
        quote = str(row.get("support_quote") or "")
        quote_start = chunk.text.find(quote) if quote else -1
        if quote_start < 0:
            return None
        try:
            subject_type = KnowledgeNodeType(str(row.get("subject_type") or "").casefold())
            object_type = KnowledgeNodeType(str(row.get("object_type") or "").casefold())
            relation = KnowledgeRelationType(str(row.get("relation") or "").casefold())
        except ValueError:
            return None
        if subject_type not in SEMANTIC_NODE_TYPES or object_type not in SEMANTIC_NODE_TYPES:
            return None
        if relation not in SEMANTIC_RELATIONS:
            return None
        subject = self._endpoint(row, "subject", subject_type)
        object_ = self._endpoint(row, "object", object_type)
        if not subject.canonical_name or not object_.canonical_name:
            return None
        if self._invalid_endpoint(subject) or self._invalid_endpoint(object_):
            return None
        if subject_type == KnowledgeNodeType.PERSON and subject.canonical_name not in quote:
            return None
        if object_type == KnowledgeNodeType.PERSON and object_.canonical_name not in quote:
            return None
        return KnowledgeTripleAssertion(
            document_version_id=document.version_id, evidence_id=evidence_id,
            section_id=self._section_id(document, evidence_id), subject=subject,
            relation=relation, object=object_, support_quote=quote,
            quote_start=quote_start, quote_end=quote_start + len(quote),
        )

    @staticmethod
    def _invalid_endpoint(endpoint: KnowledgeEndpoint) -> bool:
        normalized = " ".join(endpoint.canonical_name.casefold().split()).strip("`*_-. ")
        if normalized in _GENERIC_NAMES or len(normalized) < 2:
            return True
        if endpoint.node_type == KnowledgeNodeType.EVENT:
            return not any(marker in normalized for marker in _EVENT_MARKERS)
        if endpoint.node_type == KnowledgeNodeType.SPRINT:
            return not any(marker in normalized for marker in _SPRINT_MARKERS)
        return False

    @staticmethod
    def _endpoint(row: dict[str, Any], prefix: str, node_type: KnowledgeNodeType) -> KnowledgeEndpoint:
        name = " ".join(str(row.get(f"{prefix}_name") or "").split())
        aliases = tuple(dict.fromkeys(
            " ".join(str(value).split()) for value in row.get(f"{prefix}_aliases") or []
            if str(value).strip()
        ))
        attributes = tuple(
            (key, " ".join(str(row.get(key) or "").split()))
            for key in ("status", "time", "version") if str(row.get(key) or "").strip()
        )
        return KnowledgeEndpoint(
            node_type=node_type, canonical_name=name, aliases=aliases,
            description=" ".join(str(row.get(f"{prefix}_description") or "").split()),
            attributes=attributes,
        )

    def _chat(
        self, title: str, evidence: list[dict[str, Any]], *, max_assertions: int = 8,
    ) -> dict[str, Any]:
        self.request_count += 1
        node_types = sorted(item.value for item in SEMANTIC_NODE_TYPES)
        relations = sorted(item.value for item in SEMANTIC_RELATIONS)
        prompt = {
            "task": "Extract a compact navigation graph from supplied Evidence.",
            "ontology_version": self.ontology_version,
            "rules": [
                "Return only explicitly stated named entities and relations.",
                "Copy evidence_id exactly and support_quote as an exact contiguous substring of that Evidence content.",
                "Do not create project, module, document, section, version, number, status, date, table-cell, or generic entity nodes.",
                "Keep status, time, and version as optional string attributes.",
                "Create PERSON only when the quote explicitly names participation, responsibility, assignment, or delivery.",
                "Prefer specific reusable names; omit vague nodes such as system, work, feature, technology, retrieval, meeting, or task alone.",
                f"Return at most {max_assertions} high-value assertions per batch and JSON only.",
            ],
            "document_title": title,
            "evidence": evidence,
        }
        properties = {
            "evidence_id": {"type": "string", "maxLength": 160},
            "support_quote": {"type": "string", "maxLength": 800},
            "subject_type": {"type": "string", "enum": node_types},
            "subject_name": {"type": "string", "maxLength": 160},
            "subject_aliases": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 120}},
            "subject_description": {"type": "string", "maxLength": 320},
            "relation": {"type": "string", "enum": relations},
            "object_type": {"type": "string", "enum": node_types},
            "object_name": {"type": "string", "maxLength": 160},
            "object_aliases": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 120}},
            "object_description": {"type": "string", "maxLength": 320},
            "status": {"type": "string", "maxLength": 120},
            "time": {"type": "string", "maxLength": 120},
            "version": {"type": "string", "maxLength": 120},
        }
        required = list(properties)
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps({
                "model": self.model, "temperature": 0, "max_tokens": 2400,
                "response_format": {"type": "json_schema", "json_schema": {
                    "name": "evidence_bound_layered_knowledge_graph", "strict": True,
                    "schema": {"type": "object", "properties": {"assertions": {
                        "type": "array", "maxItems": max_assertions, "items": {
                            "type": "object", "properties": properties,
                            "required": required, "additionalProperties": False,
                        }}}, "required": ["assertions"], "additionalProperties": False,
                    },
                }},
                "messages": [
                    {"role": "system", "content": "Extract an Evidence-grounded navigation graph. Never invent facts or source identifiers."},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
            }, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = payload["choices"][0]["message"]["content"]
        if isinstance(content, dict):
            value = content
        else:
            text = str(content).strip()
            if text.startswith("```"):
                text = text.strip("`")
                if text.startswith("json"):
                    text = text[4:].lstrip()
            value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError("knowledge extractor must return a JSON object")
        return value

    @staticmethod
    def _section_id(document: Document, evidence_id: str) -> str:
        for section in document.sections:
            if evidence_id in section.evidence_ids:
                return section.id
        return ""


def assertion_to_dict(assertion: KnowledgeTripleAssertion) -> dict[str, Any]:
    return {
        "document_version_id": assertion.document_version_id,
        "evidence_id": assertion.evidence_id, "section_id": assertion.section_id,
        "subject": _endpoint_to_dict(assertion.subject),
        "relation": KnowledgeRelationType(assertion.relation).value,
        "object": _endpoint_to_dict(assertion.object),
        "support_quote": assertion.support_quote,
        "quote_start": assertion.quote_start, "quote_end": assertion.quote_end,
    }


def assertion_from_dict(value: dict[str, Any]) -> KnowledgeTripleAssertion:
    return KnowledgeTripleAssertion(
        document_version_id=str(value["document_version_id"]),
        evidence_id=str(value["evidence_id"]), section_id=str(value.get("section_id") or ""),
        subject=_endpoint_from_dict(value["subject"]),
        relation=KnowledgeRelationType(value["relation"]),
        object=_endpoint_from_dict(value["object"]),
        support_quote=str(value["support_quote"]), quote_start=int(value["quote_start"]),
        quote_end=int(value["quote_end"]),
    )


def _endpoint_to_dict(endpoint: KnowledgeEndpoint) -> dict[str, Any]:
    return {"node_type": KnowledgeNodeType(endpoint.node_type).value, "canonical_name": endpoint.canonical_name,
            "aliases": list(endpoint.aliases), "description": endpoint.description,
            "attributes": [list(item) for item in endpoint.attributes]}


def _endpoint_from_dict(value: dict[str, Any]) -> KnowledgeEndpoint:
    return KnowledgeEndpoint(
        node_type=KnowledgeNodeType(value["node_type"]), canonical_name=str(value["canonical_name"]),
        aliases=tuple(value.get("aliases") or ()), description=str(value.get("description") or ""),
        attributes=tuple((str(key), str(item)) for key, item in value.get("attributes") or ()),
    )
