from tests.grounding_helpers import grounded_model, control_response
"""Real Chat dispatcher, tools and source guard with controlled model/native IO."""

import pytest

from agent.agent import Agent
from agent.schemas.chat import ChatRequest
from agent.schemas.query_plan import QueryIntent, QueryPlan
from agent.service.permission_service import PermissionResolutionError
from toolset.tool_layer import BaseTool
from toolset.tool_layer.evidence_metadata import source_metadata
from tests.integration.test_chat_evidence_security import fixture  # noqa: F401


class SourceTool(BaseTool):
    name = "search_documents"
    description = "Controlled enterprise source"
    parameters = {"type": "object", "properties": {"query": {"type": "string"}}}

    def __init__(self, documents):
        self.documents, self.calls = documents, []

    def execute(self, **arguments):
        pytest.fail("Search must use the structured contract")

    def search_direct(self, **arguments):
        self.calls.append(arguments)
        assert arguments["filters"]["doc_ids"] == ["doc1"]
        document = self.documents["doc1"]
        return [{"doc_id": "doc1", "chunk_id": "doc1_chunk_0", "chunk_index": 0,
                 "title": document["title"], "chunk_text": document["content"], "score": 1.0,
                 **source_metadata(document)}]

    def search(self, **arguments):
        pytest.fail("Fast must use direct retrieval without scope inference")


class CountingModel:
    def __init__(self, answer="Grounded answer [1]", after_call=None):
        self.calls, self.answer, self.after_call = [], answer, after_call

    @grounded_model
    def chat(self, messages, tools=None, **kwargs):
        if tools:
            import json
            self.calls.append(messages)
            return control_response(**json.loads(self.answer))
        self.calls.append(messages)
        if self.after_call:
            self.after_call()
        return {"content": self.answer}

    def stream_chat(self, messages, tools=None, **kwargs):
        yield {"content": self.chat(messages, tools, **kwargs)["content"]}


@pytest.mark.parametrize("stream", [False, True])
def test_fast_enters_same_pipeline_once_with_real_source_guard(fixture, monkeypatch, stream):
    guard, _, documents, *_ = fixture
    model, tool = CountingModel(), SourceTool(documents)
    agent = Agent(llm=model, tools=[tool], permission_service=guard.permissions)
    monkeypatch.setattr(agent.runner, "run", lambda *args, **kwargs: pytest.fail("Entered Thinking"))
    assert not hasattr(agent, "query_understanding")
    assert not hasattr(agent, "title_llm")
    request = ChatRequest(query="Compare the complete end-to-end flow", user_id="alice", weight_mode="fast", is_first_message=True)
    if stream:
        events = list(agent.stream_chat(request))
        done = events[-1][1]
        assert done["status"] == "success"
        assert done["evidence_provenance"]["complete"]
        assert [payload["content"] for name, payload in events if name == "token"] == ["Grounded answer [1]"]
    else:
        response = agent.chat(request)
        assert response.status == "success" and response.evidence_provenance.complete
        assert response.diagnostics is None or isinstance(response.diagnostics, dict)
    assert len(model.calls) == len(tool.calls) == 1
    assert tool.calls[0]["query"] == request.query


def test_fast_invalid_citation_never_releases_a_streamed_draft(fixture):
    guard, _, documents, *_ = fixture
    model = CountingModel("Unsupported source [99]")
    agent = Agent(llm=model, tools=[SourceTool(documents)], permission_service=guard.permissions)
    events = list(agent.stream_chat(ChatRequest(query="Question", user_id="alice", weight_mode="fast")))
    assert events[-1][1]["status"] == "quality_validation_failed"
    assert not any(name == "token" for name, _ in events)
    assert len(model.calls) == 1


@pytest.mark.parametrize("mode", ["thinking", "auto"])
@pytest.mark.parametrize("stream", [False, True])
def test_thinking_scope_clarification_is_an_agent_decision(fixture, mode, stream):
    guard, *_ = fixture
    model = CountingModel('{"action":"clarify","question":"Please specify which architecture."}')
    agent = Agent(llm=model, tools=[], permission_service=guard.permissions)
    request = ChatRequest(query="Explain the latest architecture", user_id="alice", weight_mode=mode)
    if stream:
        events = list(agent.stream_chat(request))
        assert events[-1][1]["status"] == "clarification_required"
        assert any(name == "token" and "which architecture" in payload["content"] for name, payload in events)
    else:
        response = agent.chat(request)
        assert response.status == "clarification_required" and "which architecture" in response.message
    assert len(model.calls) == 1


def test_fast_rechecks_source_version_after_its_only_generation(fixture):
    guard, _, documents, *_ = fixture
    def change_source():
        documents["doc1"]["content"] = "Changed source body"
    model = CountingModel(after_call=change_source)
    agent = Agent(llm=model, tools=[SourceTool(documents)], permission_service=guard.permissions)
    with pytest.raises(PermissionResolutionError, match="document_version_changed"):
        agent.chat(ChatRequest(query="Question", user_id="alice", weight_mode="fast"))
    assert len(model.calls) == 1


@pytest.mark.parametrize("mode", ["thinking", "auto"])
def test_thinking_and_auto_never_enter_fast_even_for_a_simple_question(fixture, monkeypatch, mode):
    guard, *_ = fixture
    model = CountingModel("Hello")
    class DirectModel(CountingModel):
        def chat(self, messages, tools=None, **kwargs):
            self.calls.append(messages)
            return control_response("answer") if len(self.calls) == 1 else {"content":"Hello"}
    model = DirectModel()
    agent = Agent(llm=model, tools=[], permission_service=guard.permissions)
    monkeypatch.setattr(agent.fast_pipeline, "run", lambda *args, **kwargs: pytest.fail("Entered Fast"))
    response = agent.chat(ChatRequest(query="Hello", user_id="alice", weight_mode=mode, is_first_message=False, knowledge_base_retrieval_enabled=False))
    assert response.status == "success" and response.answer == "Hello"
    assert agent.last_orchestration.execution_profile.mode.value == "thinking"
    assert len(model.calls) == 2


@pytest.mark.parametrize('stream',[False,True])
def test_thinking_rejection_retries_privately_before_verified_release(fixture,stream):
    import json
    from agent.evidence.gate import EvidenceGate
    guard, _, documents, *_=fixture
    class ThinkingTool(SourceTool):
        def search(self,**arguments):
            return self.search_direct(**arguments)
    class Model:
        def __init__(self):self.calls=[]
        def chat(self,messages,tools=None,**kwargs):
            self.calls.append((messages,tools))
            count=len(self.calls)
            if count==1:
                return {'tool_calls':[{'id':'search','function':{'name':'search_documents','arguments':'{"query":"evidence"}'}}]}
            if tools:return control_response("answer")
            return {'content':json.dumps({'answer':'Rejected candidate' if count==3 else 'Verified candidate','claims':[{'text':'Rejected candidate' if count==3 else 'Verified candidate',
                'supports':[{'citation_id':1,'quote':'Authorized original evidence.'}]}]})}
    class Verifier:
        def __init__(self):self.calls=0
        def check(self,binding,evidence,budget):
            self.calls+=1;budget.verify()
            return [{'claim_id':'claim_1','verdict':'not_supported' if self.calls==1 else 'supported','reason':'test boundary'}]
    model,verifier=Model(),Verifier()
    agent=Agent(llm=model,tools=[ThinkingTool(documents)],permission_service=guard.permissions,
                evidence_gate=EvidenceGate(verifier))
    request=ChatRequest(query='Describe the evidence.',user_id='alice',weight_mode='thinking')
    if stream:
        events=list(agent.stream_chat(request))
        response={**events[-1][1], 'answer':''.join(v['content'] for n,v in events if n=='token')}
        assert [v['content'] for name,v in events if name=='token']==['Verified candidate[1]']
        assert 'Rejected candidate' not in json.dumps(events) and 'minicheck_argmax' not in json.dumps(events)
        displayed = next(value for name, value in events if name == 'answer-claims')
        assert displayed[0]['text'] == 'Verified candidate'
        assert set(displayed[0]) == {'claim_id', 'text', 'start', 'end', 'supports'}
    else:
        response=agent.chat(request).model_dump()
    assert response['status']=='success' and response['answer']=='Verified candidate[1]'
    assert response['evidence_provenance']['complete']
    assert len(model.calls)==5 and verifier.calls==2


def test_thinking_source_change_during_verification_prevents_release(fixture):
    import json
    from agent.evidence.gate import EvidenceGate
    guard, _, documents, *_=fixture
    class ThinkingTool(SourceTool):
        def search(self,**arguments):return self.search_direct(**arguments)
    class Model:
        calls=0
        def chat(self,messages,tools=None,**kwargs):
            self.calls+=1
            if self.calls==1:
                return {'tool_calls':[{'id':'s','function':{'name':'search_documents','arguments':'{"query":"evidence"}'}}]}
            if tools:return control_response('answer')
            return {'content':json.dumps({'answer':'Evidence exists.','claims':[{'text':'Evidence exists.',
                'supports':[{'citation_id':1,'quote':'Authorized original evidence.'}]}]})}
    class Verifier:
        def check(self,binding,evidence,budget):
            documents['doc1']['content']='Changed body during verification.'
            return [{'claim_id':'claim_1','verdict':'supported'}]
    agent=Agent(llm=Model(),tools=[ThinkingTool(documents)],permission_service=guard.permissions,
        evidence_gate=EvidenceGate(Verifier()))
    events=agent.stream_chat(ChatRequest(query='Describe the evidence.',user_id='alice',weight_mode='thinking'))
    released=[]
    with pytest.raises(PermissionResolutionError,match='document_version_changed'):
        for event in events:released.append(event)
    assert not any(name=='token' for name,_ in released)
