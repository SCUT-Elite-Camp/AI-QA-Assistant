"""Thinking business contracts with controlled model/tool/classifier boundaries."""
from copy import deepcopy
import json
from types import SimpleNamespace
import pytest

from tests.grounding_helpers import control_response
from agent.runtime.decisions import CONTROL_NAMES
from agent.evidence.gate import EvidenceGate, VerificationUnavailable
from agent.evidence.verification_context import build_verification_inputs
from agent.runtime.runner import AgentRunner
from agent.runtime.budget import RunBudget
from agent.runtime.state import StopReason
from agent.schemas.query_plan import QueryPlan
from agent.schemas.tool_execution import Evidence, ToolExecutionResult
from agent.service.access_guard import CURRENT_ACCESS_GUARD
from agent.service.permission_service import PermissionResolutionError

pytestmark = pytest.mark.no_storage
NAMES = ('search_documents', 'find_documents', 'get_document', 'search_library', 'search_attachments')


class Registry:
    def to_openai_schemas(self):
        return [{"type":"function", "function":{"name":n, "description":n, "parameters":{"type":"object"}}}
                for n in (*NAMES, 'wiki_search')]


class Model:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []
    def chat(self, messages, tools=None, **kwargs):
        self.calls.append(deepcopy((messages, tools, kwargs)))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value()
        if isinstance(value, str) and tools and value.startswith('{'):
            decision=json.loads(value)
            if 'action' in decision:
                return control_response(**decision)
        return {"content":value} if isinstance(value, str) else value


def tool(name='search_documents', **arguments):
    return {"tool_calls":[{"id":"call", "function":{"name":name, "arguments":json.dumps(arguments)}}]}


def draft(text='The release is planned.', quote='The release is planned.'):
    return json.dumps({"answer":text,"claims":[{"text":text,"supports":[{"citation_id":1,"quote":quote}]}]})


def evidence(doc='a', text='The release is planned.', source='knowledge'):
    return Evidence(doc_id=doc, chunk_id=doc+'::chunk_0', title='Release', content=text,
                    score=1, retrieval_query='release', retrieval_mode='hybrid', source_type=source,
                    source_scope='enterprise', evidence_ref=doc+':0', content_hash='original-hash', source_version='7')


class Executor:
    def __init__(self, results=None):
        self.calls, self.results = [], results
    def execute(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        if self.results is not None:
            value = self.results.pop(0)
            if isinstance(value, Exception):
                raise value
            return value
        return ToolExecutionResult(tool_call_id='call', tool_name=kwargs['tool_name'], success=True, evidence=[evidence()])


class Verifier:
    def __init__(self, *verdicts):
        self.verdicts, self.inputs = list(verdicts or ['supported']), []
    def check(self, binding, evidence, budget):
        prepared = build_verification_inputs(binding, evidence)
        self.inputs.append(prepared)
        verdict = self.verdicts.pop(0)
        if isinstance(verdict, Exception):
            raise verdict
        rows=[]
        for item in prepared:
            budget.verify()
            rows.append({'claim_id':item.claim_id,'text':item.claim,'verdict':verdict,'reason':'controlled_classifier'})
        return rows


def run(*responses, verifier=None, executor=None, budget=None, **kwargs):
    model = Model(*responses)
    executor = executor or Executor()
    verifier = verifier or Verifier()
    runner = AgentRunner(model, Registry())
    result = runner.run(QueryPlan(original_query='What is the release status?', standalone_query='unused rewrite',
        filters={'doc_ids':['a','b']}), trace_id='thinking-test', tool_executor=executor,
        evidence_gate=EvidenceGate(verifier), budget=budget, allowed_tools=NAMES, **kwargs)
    return result, model, executor, verifier


def test_first_request_is_original_question_and_tools_without_presearch_or_classifier():
    result, model, executor, _ = run('{"action":"clarify","question":"Which release?"}')
    messages, tools, _ = model.calls[0]
    assert any(m['content']=='What is the release status?' for m in messages)
    assert 'rewrite search queries' in messages[0]['content'] and 'clarifying question' in messages[0]['content']
    assert {t['function']['name'] for t in tools} == set(NAMES) | CONTROL_NAMES
    assert not executor.calls and result.message == 'Which release?'
    assert result.stop_reason == StopReason.CLARIFICATION_REQUIRED
    assert 'ANSWER_GROUNDING' not in messages[0]['content']
    assert model.calls[0][2]['tool_choice']=='required'


def test_model_controls_rewrite_and_answer_uses_separate_tool_free_protocol():
    result, model, executor, verifier = run(tool(query='release lifecycle revised query'), '{"action":"answer"}', draft())
    assert result.stop_reason == StopReason.FINAL_ANSWER
    assert result.answer == 'The release is planned.[1]'
    assert executor.calls[0]['arguments']['query'] == 'release lifecycle revised query'
    assert executor.calls[0]['arguments']['filters']['doc_ids']==['a','b']
    assert model.calls[-1][1] is None and 'ANSWER_GROUNDING' in model.calls[-1][0][0]['content']
    assert result.budget['model_calls']==3 and result.budget['tool_calls']==1 and result.budget['verifications']==1
    assert verifier.inputs[0][0].status=='ready'


def test_minicheck_rejection_returns_to_agent_and_replacement_is_reverified():
    result, model, _, verifier = run(tool(query='release'), '{"action":"answer"}',
        draft('The release is approved.'), '{"action":"answer"}', draft(),
        verifier=Verifier('not_supported','supported'))
    assert result.stop_reason == StopReason.FINAL_ANSWER and 'planned' in result.answer
    assert len(verifier.inputs)==2 and len(model.calls)==5
    feedback=model.calls[3][0][-1]['content']
    assert 'not_supported' in feedback and 'approved' in feedback and 'not proof of falsity' in feedback
    assert result.verification['accepted'] and result.budget['verifications']==2


def test_rejected_answer_is_never_released_when_budget_runs_out():
    budget=RunBudget(3,5,30000,150000,10,60)
    result, model, _, _ = run(tool(query='release'), '{"action":"answer"}', draft(),
        verifier=Verifier('not_supported'), budget=budget)
    assert result.stop_reason==StopReason.QUALITY_VALIDATION_FAILED and not result.answer
    assert result.error_code=='thinking_model_call_budget_exceeded' and len(model.calls)==3


def test_invalid_quote_is_repaired_before_classifier_is_called():
    result, _, _, verifier=run(tool(query='release'),'{"action":"answer"}',draft(quote='Fabricated'),
        '{"action":"answer"}',draft())
    assert result.stop_reason==StopReason.FINAL_ANSWER and len(verifier.inputs)==1


def test_verifier_unavailable_is_distinct_from_unsupported_and_no_unchecked_answer():
    result, model, _, _=run(tool(query='release'),'{"action":"answer"}',draft(),
        verifier=Verifier(VerificationUnavailable('minicheck_load_failed')))
    assert result.stop_reason==StopReason.TOOL_ERROR and not result.answer and len(model.calls)==3
    assert result.error_code=='minicheck_load_failed'


def test_required_private_source_cannot_be_substituted_with_enterprise():
    result, model, _, verifier=run(tool(query='release'),'{"action":"answer"}',
        '{"action":"insufficient"}', required_sources=('personal',))
    assert result.stop_reason==StopReason.NO_RELEVANT_CONTEXT and not verifier.inputs
    assert 'required_source_evidence_missing' in model.calls[-1][0][-1]['content']


def test_catalog_is_not_answer_evidence_and_batch_full_reads_are_projected_once():
    text='The release is planned.'
    results=[ToolExecutionResult(tool_call_id='call',tool_name='find_documents',success=True,
        data={'documents':[{'doc_id':'a','title':'Release'},{'doc_id':'b','title':'Rollout'}]}),
        ToolExecutionResult(tool_call_id='call',tool_name='get_document',success=True,
        evidence=[evidence(),evidence('b','Rollout is scheduled.')],
        data={'documents':[{'doc_id':'a','content':text,'chunks':[{'text':text}]},
                           {'doc_id':'b','content':'Rollout is scheduled.'}]})]
    result, model, executor, _=run(tool('find_documents'),tool('get_document',doc_ids=['a','b']),
        '{"action":"answer"}',draft(),executor=Executor(results))
    assert result.stop_reason==StopReason.FINAL_ANSWER
    assert executor.calls[1]['arguments']['doc_ids']==['a','b']
    context=model.calls[2][0][-1]['content']
    assert context.count(text)==1 and 'chunks' not in context and 'content_hash' not in context
    assert len(json.loads(context.split('\n',1)[1])['documents'])==2


@pytest.mark.parametrize('name,args',[
    ('search_documents',{'query':'x','filters':{'doc_ids':['outside']}}),
    ('get_document',{'doc_ids':['outside']})])
def test_model_cannot_widen_explicit_document_scope(name,args):
    result, _, executor, _=run(tool(name,**args),'{"action":"insufficient"}')
    if name=='get_document':
        assert not executor.calls
    else:
        assert executor.calls[0]['arguments']['filters']['doc_ids']==[]
    assert not result.answer


def test_forged_wiki_call_is_rejected_even_if_registered():
    result, _, executor, _=run(tool('wiki_search',query='x'))
    assert result.error_code=='tool_not_allowed' and not executor.calls


def test_permission_failure_during_retry_never_reaches_next_model():
    checks=[]
    def check():
        checks.append(1)
        if len(checks)>9:
            raise PermissionResolutionError('source_access_revoked', 403)
    token=CURRENT_ACCESS_GUARD.set(SimpleNamespace(check_dependencies=check))
    try:
        with pytest.raises(PermissionResolutionError,match='source_access_revoked'):
            run(tool(query='release'),'{"action":"answer"}',draft(),'{"action":"answer"}',draft(),
                verifier=Verifier('not_supported','supported'))
    finally:
        CURRENT_ACCESS_GUARD.reset(token)


@pytest.mark.parametrize('budget,code',[
    (RunBudget(10,1,30000,150000,10,60),'thinking_tool_call_budget_exceeded'),
    (RunBudget(10,5,100,150000,10,60),'thinking_context_budget_exceeded'),
    (RunBudget(10,5,30000,1,10,60),'thinking_token_reservation_exceeded')])
def test_all_limits_terminate_without_answer(budget,code):
    result, _, _, _=run(tool(query='release'),tool(query='other'),budget=budget)
    assert result.error_code==code and not result.answer


def test_provider_errors_consume_one_call_and_do_not_spawn_fallback_generation():
    result, model, _, _=run(RuntimeError('provider unavailable'))
    assert result.stop_reason==StopReason.LLM_ERROR and len(model.calls)==1
    assert result.budget['model_calls']==1


def test_native_control_cannot_bypass_or_mix_with_source_actions():
    mixed=tool(query='release')
    mixed['tool_calls']+=control_response('answer')['tool_calls']
    result, model, executor, _=run(mixed,control_response('insufficient'))
    assert not executor.calls and result.stop_reason==StopReason.NO_RELEVANT_CONTEXT
    assert 'invalid_control_action' in model.calls[-1][0][-1]['content']


def test_content_only_control_is_not_mistaken_for_a_valid_native_call():
    result, model, _, _=run({'content':'{"action":"answer"}'},control_response('clarify',question='Which release?'))
    assert result.stop_reason==StopReason.CLARIFICATION_REQUIRED
    assert 'native_action_required' in model.calls[-1][0][-1]['content']


def test_unverified_input_can_return_to_agent_for_more_evidence():
    result,model,_,verifier=run(tool(query='release'),control_response('answer'),draft(),
        tool(query='release conditions'),control_response('answer'),draft(),
        verifier=Verifier('unverified','supported'))
    assert result.stop_reason==StopReason.FINAL_ANSWER and len(verifier.inputs)==2
    assert 'unverified' in model.calls[3][0][-1]['content']


def test_each_selected_attachment_requires_actual_current_evidence():
    item=evidence('att_one',source='attachment')
    executor=Executor([ToolExecutionResult(tool_call_id='a',tool_name='search_attachments',success=True,evidence=[item])])
    result,model,_,verifier=run(tool('search_attachments',query='release'),control_response('answer'),
        control_response('insufficient'), executor=executor, required_sources=('attachment',),
        required_attachments=('att_one','att_two'))
    assert result.stop_reason==StopReason.NO_RELEVANT_CONTEXT and not verifier.inputs
    assert 'att_two' in model.calls[-1][0][-1]['content']
    assert 'mode' not in executor.calls[0]['arguments']


def test_deadline_expiring_during_model_does_not_release_clarification():
    budget=RunBudget(10,8,30000,150000,10,60)
    def slow_response():
        budget.started-=120
        return control_response('clarify',question='Which release?')
    result,model,_,_=run(slow_response,budget=budget)
    assert result.stop_reason==StopReason.POLICY_LIMIT and not result.answer and not result.message
    assert len(model.calls)==1 and result.error_code=='thinking_deadline_exceeded'
