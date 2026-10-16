from tests.grounding_helpers import grounded_model
"""Exercise catalog selection and batch reading through the real tool boundary."""

import json
from types import SimpleNamespace

import pytest

from agent.evidence import EvidenceGate
from agent.policy import IntentPolicyRouter
from agent.runtime import AgentRunner, StopReason
from agent.schemas.query_plan import QueryIntent, QueryPlan
from agent.service.audit_service import AuditService
from agent.tools import ToolExecutor, ToolRegistryAdapter
from toolset.tool_layer import BaseTool, FindDocumentsTool, GetDocumentTool, ToolRegistry


pytestmark = pytest.mark.no_storage


class Search(BaseTool):
    name = "search_documents"
    description = "Search fixture documents."
    parameters = {"type": "object", "properties": {"query": {"type": "string"}}}

    def __init__(self, directory, rows):
        self.documents_dir = directory
        self.rows = rows
        self.bm25_index = SimpleNamespace(search=lambda *args, **kwargs: [])

    def execute(self, **kwargs):
        raise AssertionError("structured search required")

    def search(self, **kwargs):
        return self.rows


class Model:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    @grounded_model
    def chat(self, messages, tools=None):
        self.calls.append((list(messages), tools))
        return next(self.responses)


def call(name, **arguments):
    return {"role": "assistant", "tool_calls": [{"id": f"call-{name}",
        "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}


def run(tmp_path, rows, responses, intent=QueryIntent.KNOWLEDGE_QA):
    for doc_id in ("alpha", "beta"):
        (tmp_path / f"{doc_id}.json").write_text(json.dumps({
            "doc_id": doc_id, "title": doc_id.title(), "version": "1",
            "content": f"Heading for {doc_id}\nFull details of {doc_id}.",
            "chunks": [{"index": 0, "text": f"Full details of {doc_id}."}],
        }), encoding="utf-8")
    search = Search(tmp_path, rows)
    registry = ToolRegistryAdapter(ToolRegistry(tools=[search,
        FindDocumentsTool(search), GetDocumentTool(tmp_path)]))
    model = Model(responses)
    plan = QueryPlan(original_query="What information is available?",
        standalone_query="What information is available?", intent=intent)
    runner = AgentRunner(llm=model, registry=registry, audit_service=AuditService())
    result = runner.run(plan, policy=IntentPolicyRouter().route(plan),
        tool_executor=ToolExecutor(registry), evidence_gate=EvidenceGate(min_score=0.5), trace_id="catalog-read")
    return result, model


@pytest.mark.parametrize("initial_score", [None, 0.1, 0.8])
def test_agent_can_browse_catalog_after_empty_or_partial_topk_and_batch_read(tmp_path, initial_score):
    rows = [{"doc_id": "alpha", "chunk_id": "alpha::chunk_0", "chunk_index": 0,
        "title": "Alpha", "chunk_text": "Full details of alpha.", "score": initial_score}] if initial_score is not None else []
    result, model = run(tmp_path, rows, [call("search_documents", query="question"),
        call("find_documents"), call("get_document", doc_ids=["alpha", "beta"]),
        {"role": "assistant", "content": "The documents describe alpha and beta [1]."}])
    assert result.stop_reason == StopReason.FINAL_ANSWER
    assert [record.tool_name for record in result.tool_calls] == [
        "search_documents", "find_documents", "get_document"]
    assert {item["doc_id"] for item in result.evidence} == {"alpha", "beta"}
    assert all(not item["chunk_id"].endswith("::document") for item in result.evidence)
    assert all(tools for _, tools in model.calls[:3])
    catalog = next(message for message in model.calls[2][0] if message.get("name") == "find_documents")
    assert json.loads(catalog["content"])["total_documents"] == 2
    read = next(message for message in model.calls[3][0] if message.get("name") == "get_document")
    assert "Heading for alpha" in read["content"] and "Heading for beta" in read["content"]
    assert "Citation evidence:" in read["content"]


def test_catalog_is_metadata_and_cannot_support_a_factual_answer(tmp_path):
    result, _ = run(tmp_path, [], [call("find_documents")] +
        [{"role": "assistant", "content": "Unsupported factual answer."}] * 5)
    assert result.stop_reason == StopReason.NO_RELEVANT_CONTEXT
    assert result.evidence == []


def test_document_search_can_list_catalog_without_fabricated_citations(tmp_path):
    result, _ = run(tmp_path, [], [call("find_documents"),
        {"role": "assistant", "content": "Available documents: Alpha, Beta."}], QueryIntent.DOCUMENT_SEARCH)
    assert result.stop_reason == StopReason.FINAL_ANSWER
    assert result.evidence == []
