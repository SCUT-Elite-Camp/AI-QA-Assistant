from types import SimpleNamespace

import pytest

from agent.agent import Agent
from agent.schemas.chat import ChatRequest
from toolset.tool_layer.search_tool import SearchTool


@pytest.mark.parametrize('accessible, expected', [(['allowed'], ['allowed']), ([], [])])
def test_fast_stream_uses_current_search_contract_and_authorization(monkeypatch, accessible, expected):
    calls = []

    # An explicit signature catches obsolete keyword arguments instead of masking them.
    def search(self, query, top_k=5, mode='hybrid', filters=None, min_score=0.0, trace_id=None, navigation_mode='direct'):
        calls.append(filters)
        return []

    monkeypatch.setattr(SearchTool, 'search', search)
    agent = Agent(permission_service=SimpleNamespace(get_accessible_doc_ids=lambda _: accessible))
    monkeypatch.setattr(agent.query_understanding.query_planner, 'enrich', lambda *args: SimpleNamespace(sub_queries=[]))
    prompts = []
    def stream(messages):
        prompts.extend(messages)
        yield {'content': 'The selected evidence does not establish the answer.'}
    monkeypatch.setattr(agent.llm, 'stream_chat', stream)
    events = list(agent.stream_chat(ChatRequest(query='Compare the sprint counts.', weight_mode='fast', user_id='test-user', topic_doc_ids=['forbidden'], filters={'doc_ids': ['allowed', 'forbidden']})))
    assert calls == [{'doc_ids': expected}]
    assert events[-1][0] == 'done', events
    assert not any(name == 'error' for name, _ in events)
    assert 'Answer in English' in prompts[0]['content']


def test_fast_stream_respects_disabled_knowledge_base(monkeypatch):
    def forbidden_search(*args, **kwargs):
        pytest.fail('Disabled knowledge base must not be searched')
    monkeypatch.setattr(SearchTool, 'search', forbidden_search)
    agent = Agent()
    assert list(agent.stream_chat(ChatRequest(query='Hello', weight_mode='fast', knowledge_base_retrieval_enabled=False)))[-1][0] == 'done'


@pytest.mark.parametrize('checked', ['The earlier dependency has unconfirmed later status. [1]', None])
def test_dated_comparison_never_streams_unchecked_claims(monkeypatch, checked):
    from deep_research.model_report import EvidenceReportSynthesizer
    agent = Agent()
    monkeypatch.setattr(agent, '_retrieve_fast_context', lambda *args: [
        {'doc_id':'doc', 'chunk_id':'chunk', 'title':'Plan', 'snapshot_date':'2026-01-02', 'chunk_text':'Earlier dependency'}])
    monkeypatch.setattr(agent.llm, 'stream_chat', lambda *args: iter([{'content':'The old dependency still exists.'}]))
    evidence = []
    def validate(self, content, objective, sources):
        evidence.append(sources)
        return checked
    monkeypatch.setattr(EvidenceReportSynthesizer, 'repair_answer', validate)
    events = list(agent.stream_chat(ChatRequest(query='Compare dates and remaining limitations.', weight_mode='fast')))
    assert not any(name == 'error' for name, _ in events), events
    answer = ''.join(payload['content'] for name, payload in events if name == 'token')
    assert 'still exists' not in answer
    assert '2026-01-02' in evidence[0]
    assert events[-1][1]['status'] == ('success' if checked else 'quality_validation_failed')


@pytest.mark.parametrize('mode', ['fast', 'thinking'])
def test_stream_asks_for_latest_architecture_scope_without_model_call(monkeypatch, mode):
    agent = Agent()
    def forbidden_model(*args, **kwargs):
        pytest.fail('Ambiguous architecture requests must clarify before invoking the model')
    monkeypatch.setattr(agent.llm, 'stream_chat', forbidden_model)
    events = list(agent.stream_chat(ChatRequest(query='What is the latest Agent architecture?', weight_mode=mode)))
    assert events[-1][1]['status'] == 'clarification_required'
    answer = next(payload['content'] for name, payload in events if name == 'token')
    assert 'current code implementation' in answer
    assert 'planned target architecture' in answer


def test_explicit_empty_source_scope_stays_empty_for_authorized_users():
    agent = Agent(permission_service=SimpleNamespace(get_accessible_doc_ids=lambda _: ['allowed']))
    assert agent._resolve_filters(ChatRequest(query='Question', user_id='test-user', filters={'doc_ids': []})) == {'doc_ids': []}


def test_english_fallback_title_never_delays_stream_with_another_model_call(monkeypatch):
    agent = Agent()
    def forbidden_model(*args, **kwargs):
        pytest.fail('English fallback titles must not invoke a second model')
    monkeypatch.setattr(agent.title_llm, 'chat', forbidden_model)
    assert agent._generate_fallback_title('Compare Agent deliveries in W30 and W34.') == 'Compare Agent deliveries in W30 and W34.'


def test_comparison_retrieval_preserves_both_targets_and_authorization(monkeypatch):
    agent = Agent(permission_service=SimpleNamespace(get_accessible_doc_ids=lambda _: ['a', 'b']))
    monkeypatch.setattr(agent.registry, 'get_tool', lambda name: None)
    monkeypatch.setattr(agent.query_understanding.query_planner, 'enrich', lambda *args: SimpleNamespace(sub_queries=['Module X release A', 'Module X release B']))
    calls = []
    def search(**kwargs):
        calls.append(kwargs)
        doc = 'a' if kwargs['query'].endswith('A') else 'b'
        return [{'doc_id': doc, 'chunk_id': f'{doc}-{i}'} for i in range(5)]
    result = agent._retrieve_fast_context(ChatRequest(query='Compare Module X releases A and B.', user_id='test', filters={'doc_ids': ['a', 'b', 'forbidden']}), SimpleNamespace(search=search), 'trace')
    assert [r['doc_id'] for r in result[:2]] == ['a', 'b']
    assert all(call['filters'] == {'doc_ids': ['a', 'b']} for call in calls)
    assert len(result) == 10


def test_named_module_period_prefers_module_title_over_team_and_other_period():
    docs = [
        {'doc_id': 'team', 'title': 'Sprint 2027-W12 Master Delivery Report'},
        {'doc_id': 'module', 'title': 'Sprint 2027-W12 Toolset Module Deliverables'},
        {'doc_id': 'wrong-module', 'title': 'Sprint 2027-W12 Web Module Deliverables'},
        {'doc_id': 'wrong-week', 'title': 'Sprint 2027-W11 Toolset Module Deliverables'},
    ]
    assert Agent._matching_target_documents('Toolset deliveries in 2027-W12 total commits and features', docs) == ['module']


def test_english_month_reference_matches_numeric_meeting_title():
    assert Agent._matching_target_documents('Meeting minutes September 8', [
        {'doc_id': 'earlier', 'title': 'Meeting Minutes 2027 07 08'},
        {'doc_id': 'target', 'title': 'Meeting+Minutes+of+2027+09+08'},
    ]) == ['target']


def test_discovery_handles_unrestricted_filters_without_none_mapping(monkeypatch):
    agent = Agent()
    monkeypatch.setattr(agent.query_understanding.query_planner, 'enrich', lambda *args: SimpleNamespace(sub_queries=['Toolset 2027-W12', 'Toolset 2027-W13']))
    discovery = SimpleNamespace(execute=lambda **kwargs: {'documents': [{'doc_id': 'target', 'title': kwargs['query']}]})
    monkeypatch.setattr(agent.registry, 'get_tool', lambda name: discovery if name == 'find_documents' else None)
    calls = []
    agent._retrieve_fast_context(ChatRequest(query='Compare Toolset releases.'), SimpleNamespace(search=lambda **kwargs: calls.append(kwargs) or []), 'trace')
    assert all(c['filters'] == {'doc_ids': ['target']} for c in calls)


def test_short_target_note_retains_limitations_beyond_search_top_k(monkeypatch):
    agent = Agent(permission_service=SimpleNamespace(get_accessible_doc_ids=lambda _: ['allowed']))
    monkeypatch.setattr(agent.query_understanding.query_planner, 'enrich', lambda *args: SimpleNamespace(sub_queries=['Toolset 2027-W12', 'Toolset 2027-W13']))
    discovery = SimpleNamespace(execute=lambda **kwargs: {'documents': [{'doc_id': 'allowed', 'title': kwargs['query']}, {'doc_id': 'forbidden', 'title': kwargs['query']}]})
    reads = []
    def read(**kwargs):
        reads.append(kwargs['doc_id'])
        return {'document': {'title': 'Notes'}, 'has_more': False, 'chunks': [{'chunk_id': f'c-{i}', 'text': 'Remaining limitation' if i == 6 else 'Context'} for i in range(7)]}
    reader = SimpleNamespace(execute=read)
    monkeypatch.setattr(agent.registry, 'get_tool', lambda name: discovery if name == 'find_documents' else reader)
    result = agent._retrieve_fast_context(ChatRequest(query='Compare Toolset releases.', user_id='test'), SimpleNamespace(search=lambda **kwargs: []), 'trace')
    assert all(doc == 'allowed' for doc in reads)
    assert any(row['chunk_text'] == 'Remaining limitation' for row in result)


def test_long_document_hits_retain_snapshot_date_without_reading_entire_doc(monkeypatch):
    agent = Agent(permission_service=SimpleNamespace(get_accessible_doc_ids=lambda _: ['allowed']))
    monkeypatch.setattr(agent.query_understanding.query_planner, 'enrich', lambda *args: SimpleNamespace(sub_queries=['Plan', 'Meeting']))
    reads = []
    def read(**kwargs):
        reads.append(kwargs)
        return {'document':{'last_updated':'2026-01-02'},'has_more':True,'chunks':[]}
    monkeypatch.setattr(agent.registry,'get_tool',lambda name: SimpleNamespace(execute=read) if name == 'get_document' else None)
    result = agent._retrieve_fast_context(ChatRequest(query='Compare dates and remaining limitations.',user_id='test'),
        SimpleNamespace(search=lambda **kwargs:[{'doc_id':'allowed','chunk_id':'chunk','chunk_text':'Earlier dependency'}]),'trace')
    assert result[0]['snapshot_date'] == '2026-01-02'
    assert reads == [{'doc_id':'allowed','limit':8}]


def test_explicit_multi_document_scope_cannot_be_starved_by_search_ranking(monkeypatch):
    agent = Agent(permission_service=SimpleNamespace(get_accessible_doc_ids=lambda _: ['plan', 'goals']))
    monkeypatch.setattr(agent.query_understanding.query_planner, 'enrich', lambda *args: SimpleNamespace(sub_queries=[]))
    reads = []
    def read(**kwargs):
        reads.append(kwargs)
        doc = kwargs['doc_id']
        return {'document': {'title': doc}, 'chunks': [{'chunk_id': doc+'_chunk_0', 'text': 'Not started' if doc=='goals' else 'Full system excluded'}], 'has_more': True}
    monkeypatch.setattr(agent.registry, 'get_tool', lambda name: SimpleNamespace(execute=read) if name=='get_document' else None)
    result = agent._retrieve_fast_context(ChatRequest(query='Has the named skill been delivered?', user_id='test', filters={'doc_ids':['plan','goals','forbidden']}),
        SimpleNamespace(search=lambda **kwargs: [{'doc_id':'plan','chunk_id':'plan_chunk_9','chunk_text':'Excluded'}]*5), 'trace')
    assert {row['doc_id'] for row in result} == {'plan','goals'}
    assert {read['doc_id'] for read in reads} == {'plan','goals'}
    assert all(read['limit']==8 for read in reads)


def test_fast_source_metadata_is_available_to_answer_generation(monkeypatch):
    agent = Agent()
    monkeypatch.setattr(agent, '_retrieve_fast_context', lambda *args: [{'doc_id':'doc','chunk_id':'doc_chunk_5','title':'Rewriter report','source_url':'https://example.org/report','chunk_text':'Commit abc, author Sam.'}])
    calls=[]
    def stream(messages):
        calls.extend(messages)
        yield {'content':'Commit abc, author Sam. Source https://example.org/report, locator doc_chunk_5. [1]'}
    monkeypatch.setattr(agent.llm,'stream_chat',stream)
    events=list(agent.stream_chat(ChatRequest(query='Give the commit, source URL and locator.',weight_mode='fast')))
    assert events[-1][0]=='done'
    assert 'Source URL: https://example.org/report' in calls[-1]['content']
    assert 'Locator: doc_chunk_5' in calls[-1]['content']


def test_fast_never_relabels_other_module_numbers_as_requested_module(monkeypatch):
    agent=Agent()
    monkeypatch.setattr(agent,'_retrieve_fast_context',lambda *args:[{'doc_id':'agent','chunk_id':'agent_chunk_0','title':'Agent Module Lifecycle Archive','chunk_text':'W34 total commits 8, feat 3, fix 5.'}])
    monkeypatch.setattr(agent.llm,'stream_chat',lambda *args:pytest.fail('Unsupported entity counts must not be synthesized'))
    events=list(agent.stream_chat(ChatRequest(query='Give exact W34 Web commit and feat/fix counts.',weight_mode='fast')))
    answer=''.join(p['content'] for n,p in events if n=='token')
    assert 'do not establish' in answer and 'Web' in answer
    assert '8' not in answer and '3' not in answer and '5' not in answer
