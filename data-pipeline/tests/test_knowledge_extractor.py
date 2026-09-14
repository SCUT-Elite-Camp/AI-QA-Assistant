from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from models.document import Chunk, Document, DocumentSection
from pipeline.knowledge_extractor import LocalOpenAIKnowledgeExtractionProvider
from pipeline.knowledge_graph import KnowledgeEndpoint
from pipeline.knowledge_graph_job import (
    activate_knowledge_revision, build_and_activate_knowledge_graph,
)


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps({
            "choices": [{"message": {"content": json.dumps({
                "assertions": [
                    {
                        "evidence_id": "ev-1", "support_quote": "bounded execution",
                        "subject_type": "component", "subject_name": "Agent Runtime",
                        "subject_aliases": ["运行时"], "subject_description": "runtime",
                        "relation": "implements",
                        "object_type": "feature", "object_name": "bounded execution",
                        "object_aliases": [], "object_description": "bounded execution",
                        "status": "", "time": "", "version": "",
                    },
                    {
                        "evidence_id": "invented", "support_quote": "unsupported",
                        "subject_type": "concept", "subject_name": "Unsupported",
                        "subject_aliases": [], "subject_description": "",
                        "relation": "related_to", "object_type": "concept",
                        "object_name": "Other", "object_aliases": [],
                        "object_description": "", "status": "", "time": "", "version": "",
                    },
                ]
            })}}],
        }).encode()


def _document() -> Document:
    return Document(
        doc_id="doc-1", title="Architecture", content="bounded execution",
        space="RAG", address="", last_updated="", version_id="ver-1",
        chunks=[Chunk(index=0, text="bounded execution", chunk_id="ev-1")],
        sections=[DocumentSection(
            id="sec-1", version_id="ver-1", title="Runtime", level=1,
            section_path=["Architecture", "Runtime"], evidence_ids=["ev-1"],
            quality="high",
        )],
    )


def test_extractor_rejects_external_endpoint_by_default() -> None:
    with pytest.raises(ValueError, match="local endpoint"):
        LocalOpenAIKnowledgeExtractionProvider(
            base_url="https://external.example/v1", model="model",
        )


def test_extractor_drops_assertions_without_supplied_evidence() -> None:
    provider = LocalOpenAIKnowledgeExtractionProvider(
        base_url="http://127.0.0.1:11434/v1", model="local-model",
    )
    with patch("pipeline.knowledge_extractor.urlopen", return_value=_Response()):
        rows = provider.extract(_document())

    assert len(rows) == 1
    assert rows[0].evidence_id == "ev-1"
    assert rows[0].section_id == "sec-1"
    assert rows[0].support_quote == "bounded execution"
    assert (rows[0].quote_start, rows[0].quote_end) == (0, len("bounded execution"))


def test_extractor_splits_only_truncated_json_batch() -> None:
    provider = LocalOpenAIKnowledgeExtractionProvider(
        base_url="http://127.0.0.1:11434/v1", model="local-model",
    )
    evidence = [{"evidence_id": "a"}, {"evidence_id": "b"}]
    responses = [
        json.JSONDecodeError("truncated", "{", 1),
        json.JSONDecodeError("truncated", "{", 1),
        {"assertions": []},
    ]

    def chat(_title, _evidence, *, max_assertions):
        value = responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    with patch.object(provider, "_chat", side_effect=chat) as mocked:
        assert provider._rows_with_split_retry("Title", evidence) == []
    assert mocked.call_count == 3
    assert [call.kwargs["max_assertions"] for call in mocked.call_args_list] == [8, 4, 2]


def test_extractor_rejects_generic_and_mistyped_event_nodes() -> None:
    provider = LocalOpenAIKnowledgeExtractionProvider(
        base_url="http://127.0.0.1:11434/v1", model="local-model",
    )

    assert provider._invalid_endpoint(KnowledgeEndpoint(
        node_type="concept", canonical_name="retrieval",
    )) is True
    assert provider._invalid_endpoint(KnowledgeEndpoint(
        node_type="event", canonical_name="query understanding",
    )) is True
    assert provider._invalid_endpoint(KnowledgeEndpoint(
        node_type="event", canonical_name="Architecture Review Meeting",
    )) is False


def test_job_activates_one_compiled_revision() -> None:
    class Provider:
        def extract(self, document):
            return []

    class Store:
        def __init__(self):
            self.calls = []

        def replace_revision(self, **kwargs):
            self.calls.append(kwargs)

    store = Store()
    result = build_and_activate_knowledge_graph(
        [_document()], provider=Provider(), store=store,
        source_scope="enterprise", owner_id="", knowledge_base_id="kb-1",
        revision="rev-1", generator_model="local-model", prompt_version="v1",
    )

    assert result["status"] == "PASS"
    assert result["activated"] is True
    assert result["nodes"] >= 2
    assert len(store.calls) == 1
    assert store.calls[0]["revision"] == "rev-1"


def test_job_preserves_old_revision_when_any_extraction_fails() -> None:
    class Provider:
        def extract(self, document):
            raise RuntimeError("local model unavailable")

    class Store:
        def __init__(self):
            self.calls = []

        def replace_revision(self, **kwargs):
            self.calls.append(kwargs)

    store = Store()
    result = build_and_activate_knowledge_graph(
        [_document()], provider=Provider(), store=store,
        source_scope="personal", owner_id="user-1", knowledge_base_id="kb-1",
        revision="rev-2", generator_model="local-model", prompt_version="v1",
    )

    assert result["status"] == "FAILED"
    assert result["activated"] is False
    assert store.calls == []


def test_activation_boundary_rejects_incomplete_batch_without_store_write() -> None:
    class Store:
        def __init__(self):
            self.calls = []

        def replace_revision(self, **kwargs):
            self.calls.append(kwargs)

    store = Store()
    result = activate_knowledge_revision(
        [_document()], assertions=[], failures=[], store=store,
        source_scope="enterprise", owner_id="", knowledge_base_id="kb-1",
        revision="rev-incomplete", generator_model="local-model", prompt_version="v1",
        expected_documents=2,
    )

    assert result["status"] == "FAILED"
    assert result["activated"] is False
    assert store.calls == []


def test_activation_boundary_rejects_empty_batch_without_store_write() -> None:
    class Store:
        def replace_revision(self, **kwargs):
            raise AssertionError("empty batch must not replace the active graph")

    result = activate_knowledge_revision(
        [], assertions=[], failures=[], store=Store(),
        source_scope="enterprise", owner_id="", knowledge_base_id="kb-1",
        revision="rev-empty", generator_model="local-model", prompt_version="v1",
        expected_documents=0,
    )

    assert result["status"] == "FAILED"
    assert result["activated"] is False
