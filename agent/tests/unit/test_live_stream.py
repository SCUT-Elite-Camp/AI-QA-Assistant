from contextvars import ContextVar
from threading import Event
from types import SimpleNamespace

import pytest

from agent.answer.generator import AnswerGenerator
from agent.service.access_guard import CURRENT_ACCESS_GUARD
from agent.streaming.live import CURRENT_STREAM_SINK, emit_model_event, threaded_events


pytestmark = pytest.mark.no_storage


def test_model_tokens_arrive_before_completion_and_keep_request_context(monkeypatch):
    monkeypatch.setattr('agent.answer.generator.answer_complexity_reasons', lambda *args, **kwargs: [])
    release = Event()
    finished = Event()
    identity = ContextVar('test_identity', default='missing')
    identity_token = identity.set('alice')
    checks = []
    class Model:
        def stream_chat(self, *args, **kwargs):
            yield {'content': 'First'}
            assert release.wait(3)
            yield {'content': ' second'}
            finished.set()
        def chat(self, *args, **kwargs):
            pytest.fail('Answer generation must use the stream method')
    def provenance():
        checks.append(identity.get())
        return SimpleNamespace(model_dump=lambda: {'complete': True, 'dependencies': []})
    guard = SimpleNamespace(provenance=provenance)
    def produce(send):
        guard_token = CURRENT_ACCESS_GUARD.set(guard)
        sink_token = CURRENT_STREAM_SINK.set(send)
        try:
            result = AnswerGenerator(complex_llm=Model()).chat([], query_plan=None,
                retrieval_attempts=0, trace_id='stream', preference='complex')
            send('done', result)
        finally:
            CURRENT_STREAM_SINK.reset(sink_token)
            CURRENT_ACCESS_GUARD.reset(guard_token)
    stream = threaded_events(produce)
    try:
        events = []
        while not any(name == 'token' for name, _ in events):
            events.append(next(stream))
        assert events[-1] == ('token', {'content': 'First'})
        assert not finished.is_set()
        release.set()
        events.extend(stream)
        assert events[-1] == ('done', {'role': 'assistant', 'content': 'First second'})
        assert checks == ['alice', 'alice', 'alice']
    finally:
        release.set()
        stream.close()
        identity.reset(identity_token)


def test_source_rejection_stops_next_model_delta():
    released = []
    def denied():
        raise RuntimeError('source_access_revoked')
    guard_token = CURRENT_ACCESS_GUARD.set(SimpleNamespace(provenance=denied))
    sink_token = CURRENT_STREAM_SINK.set(lambda name, payload: released.append((name, payload)))
    try:
        with pytest.raises(RuntimeError, match='source_access_revoked'):
            emit_model_event('token', {'content': 'must remain hidden'})
        assert released == []
    finally:
        CURRENT_STREAM_SINK.reset(sink_token)
        CURRENT_ACCESS_GUARD.reset(guard_token)
