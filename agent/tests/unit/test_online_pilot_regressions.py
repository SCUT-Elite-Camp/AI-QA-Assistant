from types import SimpleNamespace

import pytest

from agent.runtime.runner import AgentRunner
from agent.chat.thinking import ThinkingPipeline
from agent.schemas.chat import ChatRequest
from agent.schemas.query_plan import QueryPlan
from eval.deep_research_benchmark import BenchmarkRunError, _run_fast_chat
from toolset.tool_layer.search_tool import SearchTool


def test_test_index_can_be_selected_without_overwriting_the_repository_index(monkeypatch, tmp_path):
    path = tmp_path / "test-bm25.pkl"
    monkeypatch.setenv("BM25_INDEX_PATH", str(path))
    assert SearchTool().bm25_path == path


@pytest.mark.parametrize("status", ["success", "clarification_required", "no_relevant_context"])
def test_benchmark_keeps_valid_terminal_responses_for_quality_scoring(status):
    response = {"status": status, "message": "Please clarify the requested scope.", "citations": []}
    client = SimpleNamespace(request=lambda *args: response)
    result = _run_fast_chat(client, {"case_id": "case", "question": "Architecture?", "allowed_document_ids": ["doc"], "source_manifest": "manifest:case"}, 5)
    assert result["response"] == response


def test_benchmark_keeps_partial_response_for_technical_errors():
    response = {"status": "llm_error", "message": "Model unavailable", "citations": []}
    client = SimpleNamespace(request=lambda *args: response)
    with pytest.raises(BenchmarkRunError) as error:
        _run_fast_chat(client, {"case_id": "case", "question": "Architecture?", "allowed_document_ids": ["doc"], "source_manifest": "manifest:case"}, 5)
    assert error.value.partial_result["response"] == response


def test_inferred_document_title_cannot_override_explicit_source_ids():
    query = "Using the W34 Master report, confirm the production SLA."
    request = ChatRequest(query=query, filters={"doc_ids": ["authorized-id"]})
    plan = QueryPlan(original_query=query, standalone_query=query, filters={"doc_id": "W34 Master report"})
    result = ThinkingPipeline._merge_request_constraints(request, plan)
    assert result.filters == {"doc_ids": ["authorized-id"]}


def test_sprint_subquery_narrows_only_inside_the_authorized_scope(tmp_path):
    import json
    for doc_id, week in (("a", "W30"), ("b", "W34"), ("forbidden", "W34")):
        (tmp_path / f"{doc_id}.json").write_text(json.dumps({"title": f"Sprint 2026-{week} Agent"}), encoding="utf-8")
    tool = SearchTool(documents_dir=str(tmp_path))
    scope = {"doc_ids": ["a", "b"]}
    assert tool._narrow_week_scope("Agent deliveries in W34", scope) == {"doc_ids": ["b"]}
    assert tool._narrow_week_scope("Compare W30 and W34", scope) == scope
    assert tool._narrow_week_scope("Agent deliveries in W35", scope) == scope


def test_parallel_groups_keep_every_run_and_do_not_overlap_chat_requests(monkeypatch, tmp_path):
    import json
    import threading
    import eval.deep_research_benchmark as benchmark
    dataset = tmp_path / "cases.json"
    dataset.write_text(json.dumps({"cases": [{"case_id": "pilot", "question": "Check delivery."}]}), encoding="utf-8")
    barrier = threading.Barrier(2)
    chat_threads = []
    def fast(*args):
        chat_threads.append(threading.get_ident())
        barrier.wait(timeout=5)
        return {"citations": []}
    def research(*args, **kwargs):
        barrier.wait(timeout=5)
        return {"citations": []}
    monkeypatch.setattr(benchmark, "freeze_environment", lambda path: {"config_hash": "pilot-config"})
    monkeypatch.setattr(benchmark, "_run_fast_chat", fast)
    monkeypatch.setattr(benchmark, "_run_research", research)
    output = tmp_path / "results"
    args = benchmark.build_parser().parse_args(["run", "--dataset", str(dataset), "--output-dir", str(output),
                                               "--groups", "fast_chat", "deep_research_current", "--repetitions", "2", "--parallel-groups"])
    assert benchmark.run_benchmark(args) == 0
    records = [json.loads(path.read_text(encoding="utf-8")) for path in (output / "runs").glob("*/*/*.json")]
    assert len(records) == 4 and all(record["success"] for record in records)
    assert len(set(chat_threads)) == 1


def test_document_metadata_argument_cannot_break_or_replace_server_filters():
    plan = QueryPlan(original_query='Summarize goals', standalone_query='Summarize goals', filters={'doc_ids': ['allowed']})
    args = AgentRunner._scope_arguments('find_documents', {'query': 'goals', 'filters': {'doc_ids': ['forbidden']}}, plan.filters, 'bm25', 5)
    assert args == {'query': 'goals', 'filters': {'doc_ids': []}}


def test_selected_documents_do_not_inherit_guessed_metadata_filters():
    query = 'Compare deliveries in the selected documents'
    request = ChatRequest(query=query, filters={'doc_ids': ['a', 'b']})
    plan = QueryPlan(original_query=query, standalone_query=query, filters={'space': 'guessed', 'doc_type': 'sprint'})
    merged = ThinkingPipeline._merge_request_constraints(request, plan)
    assert merged.filters == {'doc_ids': ['a', 'b']}
    request = ChatRequest(query=query, filters={'doc_ids': ['a', 'b'], 'space': 'explicit'})
    plan = plan.model_copy(update={'filters': {'space': 'explicit', 'doc_type': 'sprint'}})
    assert ThinkingPipeline._merge_request_constraints(request, plan).filters == {'doc_ids': ['a', 'b'], 'space': 'explicit'}


@pytest.mark.parametrize('query', ['Retrieve details from the September 8 meeting notes', 'Read the meeting on September 8, 2026', 'Read the 2026-09-08 meeting'])
def test_dated_comparison_target_resolves_only_inside_allowed_documents(tmp_path, query):
    import json
    for doc_id, title in [('plan', 'Implementation Plan'), ('meeting', 'Meeting+Minutes+of+2026+09+08'), ('forbidden', 'Meeting 2026-09-08')]:
        (tmp_path / f'{doc_id}.json').write_text(json.dumps({'title': title}), encoding='utf-8')
    tool = SearchTool(documents_dir=str(tmp_path))
    scope = {'doc_ids': ['plan', 'meeting']}
    assert tool._narrow_dated_scope(query, scope) == {'doc_ids': ['meeting']}
    assert scope == {'doc_ids': ['plan', 'meeting']}


def test_missing_or_multiple_dates_do_not_narrow_comparison_scope(tmp_path):
    import json
    (tmp_path / 'meeting.json').write_text(json.dumps({'title': 'Meeting+Minutes+of+2026+09+08'}), encoding='utf-8')
    tool = SearchTool(documents_dir=str(tmp_path))
    scope = {'doc_ids': ['plan', 'meeting']}
    for query in ['Compare September 8 and September 9', 'Read the September 9 meeting', 'Read the 2025-09-08 meeting', 'Compare these plans']:
        assert tool._narrow_dated_scope(query, scope) == scope
    assert tool._narrow_dated_scope('Read September 8 meeting', {'doc_ids': []}) == {'doc_ids': []}
