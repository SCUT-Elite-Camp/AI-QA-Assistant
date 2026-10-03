from types import SimpleNamespace

import pytest

from agent.query.ambiguity import needs_architecture_scope
from agent.query.clarifier import Clarifier
from agent.runtime.runner import AgentRunner
from agent.answer.target_extractor import _grounded_in_query
from agent.answer.fact_coverage import identifier_tokens, normalized_fact_text
from agent.orchestration.orchestrator import AgentOrchestrator
from agent.schemas.chat import ChatRequest
from agent.schemas.query_plan import QueryPlan
from eval.deep_research_benchmark import BenchmarkRunError, _run_fast_chat
from toolset.tool_layer.search_tool import SearchTool


def test_comparison_keeps_each_queries_provenance_but_deduplicates_repeats():
    evidence = {"doc_id": "doc-a", "chunk_id": "doc-a_chunk_1", "retrieval_query": "Compare W30"}
    second = {**evidence, "retrieval_query": "Compare W34"}
    assert AgentRunner._merge_evidence([], [evidence, evidence, second]) == [evidence, second]


def test_test_index_can_be_selected_without_overwriting_the_repository_index(monkeypatch, tmp_path):
    path = tmp_path / "test-bm25.pkl"
    monkeypatch.setenv("BM25_INDEX_PATH", str(path))
    assert SearchTool().bm25_path == path


def test_ambiguous_latest_architecture_requires_scope_before_model_invocation():
    class UnexpectedLLM:
        def chat(self, *args, **kwargs):
            raise AssertionError("The deterministic scope check must run first")
    result = Clarifier(llm=UnexpectedLLM(), enabled=True).evaluate("What is the latest Agent architecture?", [])
    assert result.needs_clarification
    assert "current code implementation" in result.question
    assert not needs_architecture_scope("What is the Agent architecture as of 2026-09-08?")
    assert not needs_architecture_scope("Explain the latest architecture in branch optimization.")
    assert not needs_architecture_scope("Compare the current and planned target architectures.")


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
    result = AgentOrchestrator._merge_request_constraints(request, plan)
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


def test_shared_entity_word_does_not_make_unrequested_fields_mandatory():
    query = "Compare Agent delivery counts and bug fixes."
    assert not _grounded_in_query("agentContributors", normalized_fact_text(query), identifier_tokens(query))
    query = "List agent contributors."
    assert _grounded_in_query("agentContributors", normalized_fact_text(query), identifier_tokens(query))


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

def test_repair_subset_keeps_original_citation_numbers_and_table_tail():
    from agent.answer.completeness import AnswerCompletenessChecker
    from agent.schemas.tool_execution import Evidence
    evidence = [Evidence(doc_id='doc', chunk_id=f'chunk-{i}', title='Goals', content=('x' * 2000 + 'M10 Not started') if i == 5 else 'other', score=1, retrieval_query='Goals', retrieval_mode='bm25') for i in range(6)]
    checker = AnswerCompletenessChecker(SimpleNamespace())
    formatted = checker._format_evidence([evidence[5]], evidence)
    assert formatted.startswith('[6]')
    assert 'M10 Not started' in formatted

@pytest.mark.parametrize('policy_name', ['single_fact', 'topic_coverage', 'bilateral_coverage'])
def test_document_discovery_summary_does_not_support_factual_answers(policy_name):
    from agent.evidence import EvidenceGate
    from agent.schemas.intent_policy import IntentPolicy
    from agent.schemas.tool_execution import Evidence
    summary = Evidence(doc_id='doc', chunk_id='doc::document', title='Deliverables', content='Truncated file table', score=1, retrieval_query='test', retrieval_mode='document')
    plan = QueryPlan(original_query='test', standalone_query='test', sub_queries=['test', 'test2'])
    result = EvidenceGate().evaluate(plan, IntentPolicy(evidence_policy=policy_name), [summary], retrieval_attempt=1)
    assert not result.accepted
    assert result.eligible_evidence_count == 0
    identity = EvidenceGate().evaluate(plan, IntentPolicy(evidence_policy='document_identity'), [summary], retrieval_attempt=1)
    assert identity.accepted

def test_document_metadata_argument_cannot_break_or_replace_server_filters():
    plan = QueryPlan(original_query='Summarize goals', standalone_query='Summarize goals', filters={'doc_ids': ['allowed']})
    args = AgentRunner._apply_execution_constraints(tool_name='find_documents', arguments={'query': 'goals', 'doc_type': 'meeting', 'doc_ids': ['forbidden'], 'filters': {'doc_ids': ['forbidden']}}, query_plan=plan, mode='bm25', top_k=5)
    assert args == {'query': 'goals', 'filters': {'doc_ids': ['allowed']}, 'top_k': 5}

@pytest.mark.parametrize('query', ['Which commits implement the authentication handler?', 'Which Python files were added in the release?', 'What files changed in the patch?'])
def test_change_facts_require_contents_even_if_model_selects_document_search(query):
    from agent.query.intent_classifier import IntentClassifier
    from agent.query.intent_classifier import IntentResult
    from agent.schemas.query_plan import QueryIntent
    result = IntentClassifier._enforce_explicit_intent(query, [], IntentResult(intent=QueryIntent.DOCUMENT_SEARCH, confidence=0.9))
    assert result.intent == QueryIntent.KNOWLEDGE_QA


def test_locating_documents_about_changes_remains_document_search():
    from agent.query.intent_classifier import IntentClassifier
    from agent.query.intent_classifier import IntentResult
    from agent.schemas.query_plan import QueryIntent
    result = IntentClassifier._enforce_explicit_intent('Find documents about files added in the release', [], IntentResult(intent=QueryIntent.DOCUMENT_SEARCH, confidence=0.9))
    assert result.intent == QueryIntent.DOCUMENT_SEARCH


def test_selected_documents_do_not_inherit_guessed_metadata_filters():
    query = 'Compare deliveries in the selected documents'
    request = ChatRequest(query=query, filters={'doc_ids': ['a', 'b']})
    plan = QueryPlan(original_query=query, standalone_query=query, filters={'space': 'guessed', 'doc_type': 'sprint'})
    merged = AgentOrchestrator._merge_request_constraints(request, plan)
    assert merged.filters == {'doc_ids': ['a', 'b']}
    request = ChatRequest(query=query, filters={'doc_ids': ['a', 'b'], 'space': 'explicit'})
    plan = plan.model_copy(update={'filters': {'space': 'explicit', 'doc_type': 'sprint'}})
    assert AgentOrchestrator._merge_request_constraints(request, plan).filters == {'doc_ids': ['a', 'b'], 'space': 'explicit'}


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


def test_comparison_executor_receives_dated_child_scope(tmp_path):
    import json
    (tmp_path / 'meeting.json').write_text(json.dumps({'title': 'Meeting+Minutes+of+2026+09+08'}), encoding='utf-8')
    tool = SearchTool(documents_dir=str(tmp_path))
    calls = []
    class Executor:
        registry = SimpleNamespace(get=lambda name: tool)
        def execute(self, **kwargs):
            calls.append(kwargs['arguments'])
            return SimpleNamespace(success=True, evidence=[])
    plan = QueryPlan(original_query='Compare plan and meeting', standalone_query='Compare plan and meeting', sub_queries=['Retrieve plan details', 'Retrieve the September 8 meeting'])
    runner = AgentRunner.__new__(AgentRunner)
    runner._execute_parallel_comparison_retrieval(query_plan=plan, arguments={'filters': {'doc_ids': ['plan', 'meeting']}, 'top_k': 5, 'mode': 'bm25'}, trace_id='test', tool_call_id='call', tool_executor=Executor(), retrieval_attempt=1)
    by_query = {c['query']:c['filters'] for c in calls}
    assert by_query['Retrieve plan details'] == {'doc_ids': ['plan', 'meeting']}
    assert by_query['Retrieve the September 8 meeting'] == {'doc_ids': ['meeting']}


def test_english_answer_instruction_overrides_mixed_language_metadata_without_mutating_history():
    captured = []
    class LLM:
        def chat(self, messages, **kwargs):
            captured.extend(messages)
            return {'content': 'English answer [1].'}
    runner = AgentRunner.__new__(AgentRunner)
    runner.answer_llm = LLM()
    runner.fast_answer_llm = None
    state = SimpleNamespace(query_plan=QueryPlan(original_query='Compare the dated reports', standalone_query='Compare the dated reports'))
    messages = [{'role': 'system', 'content': 'Original evidence rules'}, {'role': 'user', 'content': '资料元数据'}]
    runner._chat_for_answer(state, messages)
    assert 'Write the entire answer in English' in captured[0]['content']
    assert messages[0]['content'] == 'Original evidence rules'


def test_english_repair_explicitly_retains_answer_language():
    from agent.answer.completeness import AnswerCompletenessChecker
    from agent.answer.schemas import AnswerCompletenessResult
    plan = QueryPlan(original_query='Summarize the goals', standalone_query='Summarize the goals')
    prompt = AnswerCompletenessChecker(SimpleNamespace())._repair_prompt(plan, 'Existing answer', [], AnswerCompletenessResult(complete=False))
    assert 'Write the entire repaired answer in English' in prompt
