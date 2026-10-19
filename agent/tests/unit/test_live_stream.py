from types import SimpleNamespace

import pytest

from agent.service.access_guard import CURRENT_ACCESS_GUARD
from agent.streaming.live import CURRENT_STREAM_SINK, emit_model_event


pytestmark = pytest.mark.no_storage


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
