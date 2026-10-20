from tests.grounding_helpers import grounded_model
"""Fast mode contract: fixed tools, unchanged question and one generation."""

from contextvars import ContextVar
from types import SimpleNamespace

import pytest

from agent.chat.fast import FastPipeline
from agent.config.settings import settings
from agent.evidence import CitationChecker
from agent.memory.coordinator import MemoryCoordinator
from agent.schemas.chat import ChatRequest
from agent.schemas.query_plan import QueryPlan, SourceIntent, SourceKind
from agent.schemas.tool_execution import Evidence, ToolExecutionResult
from agent.service.access_guard import CURRENT_ACCESS_GUARD
from agent.service.permission_service import PermissionResolutionError
from agent.streaming.live import CURRENT_STREAM_SINK

pytestmark = pytest.mark.no_storage


class Model:
    def __init__(self, answer="Answer [1]", error=None, tool_calls=None):
        self.answer, self.error, self.tool_calls = answer, error, tool_calls
        self.calls = []

    @grounded_model
    def chat(self, messages, tools=None):
        self.calls.append((messages, tools))
        assert tools is None
        if self.error:
            raise self.error
        return {"content": self.answer, "tool_calls": self.tool_calls}

    def stream_chat(self, messages, tools=None, **kwargs):
        response = self.chat(messages, tools, **kwargs)
        if response["tool_calls"]:
            yield {"tool_calls": response["tool_calls"]}
        else:
            yield {"content": response["content"]}


class Executor:
    def __init__(self, *, empty=(), failed=(), images=None):
        self.calls, self.empty, self.failed, self.images = [], empty, failed, images or []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        name = kwargs["tool_name"]
        kind = {"search_documents": "knowledge", "search_library": "personal",
                "read_attachment_context": "attachment"}[name]
        evidence = [] if name in self.empty else [Evidence(
            doc_id=kind, chunk_id=kind + "-chunk", title=kind, content=kind + " source text",
            score=1.0, source_type=kind, retrieval_query=kwargs["arguments"]["query"], retrieval_mode="hybrid",
            evidence_ref=kind + "-ref", content_hash=kind + "-hash",
            attachment_id=kind if kind == "attachment" else None,
            evidence_id=kind + "-chunk" if kind == "attachment" else None,
            content_kind="file" if self.images and kind == "attachment" else "excerpt",
        )]
        return ToolExecutionResult(tool_call_id=kwargs["tool_call_id"], tool_name=name,
            success=name not in self.failed, error_code="source_failed" if name in self.failed else "",
            evidence=evidence, data={"images": self.images if name == "read_attachment_context" else []})


def run(request=None, *, model=None, executor=None, plan=None):
    model, executor = model or Model(), executor or Executor()
    pipeline = FastPipeline(llm=model, executor=executor, memory=MemoryCoordinator(), citations=CitationChecker())
    result = pipeline.run(request or ChatRequest(query="Question"), trace_id="fast-test", query_plan=plan)
    return result, model, executor


@pytest.mark.parametrize("query", ["Compare A and B", "Explain the complete end-to-end flow", "  Preserve the original question  "])
def test_uses_original_query_once_and_never_exposes_tools(query):
    turn, model, executor = run(ChatRequest(query=query))
    assert turn.response.status == "success"
    assert len(model.calls) == len(executor.calls) == 1
    assert executor.calls[0]["arguments"]["query"] == query
    assert executor.calls[0]["direct_retrieval"] is True
    assert "Original question:\n" + query in model.calls[0][0][-1]["content"]
    assert "knowledge source text" in model.calls[0][0][-1]["content"]
    assert not hasattr(turn.result, "answer_repair_attempted")


def test_ignores_rewrite_and_subqueries_in_injected_plan():
    turn, model, executor = run(plan=QueryPlan(original_query="Question", standalone_query="Rewritten",
                                             sub_queries=["expanded A", "expanded B"]))
    assert turn.response.status == "success"
    assert executor.calls[0]["arguments"]["query"] == "Question"
    assert len(executor.calls) == len(model.calls) == 1


@pytest.mark.parametrize("missing", ["search_documents", "search_library", "read_attachment_context"])
def test_mixed_scope_reads_each_required_source_and_does_not_substitute(missing):
    plan = QueryPlan(original_query="Question", standalone_query="Question",
                     source_intent=SourceIntent(sources=list(SourceKind)))
    turn, model, executor = run(plan=plan, executor=Executor(empty={missing}))
    assert turn.response.status == "no_relevant_context"
    assert len(executor.calls) == 3
    assert model.calls == []
    assert "filters" not in executor.calls[1]["arguments"]


def test_tool_failure_ends_without_model_or_mode_fallback():
    turn, model, executor = run(executor=Executor(failed={"search_documents"}))
    assert turn.response.status in {"tool_error", "retrieval_error"}
    assert len(executor.calls) == 1 and model.calls == []


def test_no_additional_search_when_no_results():
    turn, model, executor = run(executor=Executor(empty={"search_documents"}))
    assert turn.response.status == "no_relevant_context"
    assert len(executor.calls) == 1 and not model.calls


@pytest.mark.parametrize("answer", ["Uncited answer", "Wrong source [99]", ""])
def test_invalid_answer_does_not_trigger_repair(answer):
    turn, model, executor = run(model=Model(answer))
    assert turn.response.status in {"quality_validation_failed", "llm_error"}
    assert not turn.response.answer
    assert len(model.calls) == len(executor.calls) == 1


def test_generation_failure_is_not_retried():
    turn, model, _ = run(model=Model(error=RuntimeError("provider down")))
    assert turn.response.status == "llm_error"
    assert len(model.calls) == 1


def test_model_tool_calls_are_never_executed():
    turn, model, executor = run(model=Model(tool_calls=[{"name": "get_document"}]))
    assert turn.response.status == "llm_error"
    assert len(executor.calls) == len(model.calls) == 1


def test_disabled_knowledge_base_has_no_retrieval_and_one_generation():
    turn, model, executor = run(ChatRequest(query="Hello", knowledge_base_retrieval_enabled=False), model=Model("Hello"))
    assert turn.response.status == "success"
    assert not executor.calls and len(model.calls) == 1
    assert turn.response.citations == []


def test_grouped_citations_are_normalized_without_changing_source_identity():
    turn, model, _ = run(model=Model("Answer【1】"))
    assert turn.response.answer == "Answer[1]"
    assert turn.response.citations[0].evidence_ref == "knowledge-ref"
    assert len(model.calls) == 1


@pytest.mark.parametrize("supported", [True, False])
def test_image_is_in_same_answer_call_or_fails_before_generation(monkeypatch, supported):
    monkeypatch.setattr(settings, "FAST_MODEL_SUPPORTS_IMAGES", supported)
    plan = QueryPlan(original_query="Question", standalone_query="Question",
                     source_intent=SourceIntent(sources=[SourceKind.CONVERSATION_ATTACHMENT]))
    executor = Executor(images=[{"attachment_id": "attachment", "image_url": "data:image/png;base64,AQ=="}])
    turn, model, executor = run(plan=plan, executor=executor)
    assert [call["tool_name"] for call in executor.calls] == ["read_attachment_context"]
    if supported:
        assert turn.response.status == "success" and len(model.calls) == 1
        assert model.calls[0][0][-1]["content"][2]["type"] == "image_url"
    else:
        assert turn.response.status == "unsupported" and not model.calls


def test_json_and_sse_share_steps_and_withhold_bad_citations():
    first, json_model, json_executor = run(model=Model("Missing citations"))
    released = []
    guard_token = CURRENT_ACCESS_GUARD.set(SimpleNamespace(
        check_dependencies=lambda: None,
        provenance=lambda: SimpleNamespace(model_dump=lambda: {"complete": True, "dependencies": []})))
    sink_token = CURRENT_STREAM_SINK.set(lambda name, payload: released.append((name, payload)))
    try:
        second, stream_model, stream_executor = run(model=Model("Missing citations"))
    finally:
        CURRENT_STREAM_SINK.reset(sink_token)
        CURRENT_ACCESS_GUARD.reset(guard_token)
    assert first.response.status == second.response.status == "quality_validation_failed"
    assert json_executor.calls == stream_executor.calls
    assert len(json_model.calls) == len(stream_model.calls) == 1
    assert not any(name == "token" for name, _ in released)


def test_revocation_after_generation_blocks_answer_release():
    revoked = False

    def check():
        if revoked:
            raise PermissionResolutionError("source_revoked", 403)

    class RevokingModel(Model):
        @grounded_model
        def chat(self, *args, **kwargs):
            nonlocal revoked
            answer = super().chat(*args, **kwargs)
            revoked = True
            return answer

    token = CURRENT_ACCESS_GUARD.set(SimpleNamespace(check_dependencies=check))
    try:
        with pytest.raises(PermissionResolutionError, match="source_revoked"):
            run(model=RevokingModel())
    finally:
        CURRENT_ACCESS_GUARD.reset(token)


def test_context_budget_cannot_silently_drop_a_selected_file(monkeypatch):
    monkeypatch.setattr(settings, "FAST_CONTEXT_MAX_CHARS", 30)
    class Files(Executor):
        def execute(self, **kwargs):
            result = super().execute(**kwargs)
            result.evidence.append(result.evidence[0].model_copy(update={
                "doc_id": "other-file", "attachment_id": "other-file", "chunk_id": "other-chunk",
                "content": "x" * 31,
            }))
            return result
    request = ChatRequest(query="Question", knowledge_base_retrieval_enabled=False).model_copy(update={
        "attachment_context": SimpleNamespace(allowed_attachment_ids=["attachment", "other-file"],
                                              selected_attachment_ids=["attachment", "other-file"]),
    })
    turn, model, _ = run(request, executor=Files())
    assert turn.response.status == "no_relevant_context"
    assert turn.result.error_code == "fast_context_budget_exceeded" and not model.calls


@pytest.mark.parametrize("query", ["Remember goal: Finish the report.", "What have you remembered?"])
def test_retired_fact_commands_follow_the_normal_model_path(query):
    turn, model, executor = run(ChatRequest(query=query, knowledge_base_retrieval_enabled=False),
        model=Model(answer="A normal model response."))
    assert turn.response.status == "success"
    assert turn.response.answer == "A normal model response."
    assert len(model.calls) == 1
    assert executor.calls == []
