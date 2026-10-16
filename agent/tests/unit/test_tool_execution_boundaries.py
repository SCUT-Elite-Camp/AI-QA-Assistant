"""Regression coverage for execution isolation."""

from concurrent.futures import TimeoutError as FutureTimeout
from threading import Event
from types import SimpleNamespace

import pytest

from agent.service.access_guard import CURRENT_ACCESS_GUARD
from agent.tools import ToolExecutor
from agent.tools import execution_pool
from agent.tools.execution_pool import ToolCapacityExhausted, _BoundedToolExecutor


pytestmark = pytest.mark.no_storage


def test_rerank_guard_follows_worker_context_and_is_reset(monkeypatch):
    from retrieval.reranker import BEFORE_RERANK, rerank
    monkeypatch.setenv('RERANK_ENABLED', 'true')
    events = []
    class Guard:
        def prepare_tool(self, name, arguments):return arguments
        def validate_rerank_candidates(self, name, rows):
            events.append(('rank-check', name, rows[0]['doc_id']))
        def capture_tool(self, name, data, evidence):events.append(('capture', name))
    def operation(**kwargs):
        result = rerank('Question', [{'doc_id':'allowed','chunk_text':'Original','score':1}], 1,
                        predictor=lambda pairs: [4])
        return {'ranked':len(result)}
    token = CURRENT_ACCESS_GUARD.set(Guard())
    try:
        tool = SimpleNamespace(name='echo', parameters={}, execute=operation)
        assert execute(tool).success
    finally:
        CURRENT_ACCESS_GUARD.reset(token)
    assert events == [('rank-check', 'echo', 'allowed'), ('capture', 'echo')]
    assert BEFORE_RERANK.get() is None


def execute(tool, **arguments):
    registry = SimpleNamespace(get=lambda name: tool)
    return ToolExecutor(registry).execute(
        tool_call_id="boundary-call", tool_name=tool.name,
        arguments=arguments, trace_id="boundary-trace",
    )


@pytest.mark.parametrize('method', ['search', 'search_direct'])
def test_source_denial_survives_search_wrapper_and_executor(monkeypatch, tmp_path, method):
    import json
    from agent.service.permission_service import PermissionResolutionError
    from retrieval.reranker import BEFORE_RERANK
    from tool_layer.search_tool import SearchTool

    monkeypatch.setenv('RERANK_ENABLED', 'true')
    (tmp_path / 'doc.json').write_text(json.dumps({'doc_id': 'doc', 'content': 'Secret',
        'chunks': [{'index': 0, 'chunk_id': 'doc_chunk_0', 'text': 'Secret'}]}), encoding='utf-8')
    class Backend:
        def search(self, *args, **kwargs):
            return [{'doc_id': 'doc', 'chunk_index': 0, 'chunk_text': 'Secret', 'score': 1}]
    class Guard:
        def prepare_tool(self, name, arguments): return arguments
        def validate_rerank_candidates(self, name, rows):
            assert rows[0]['doc_id'] == 'doc'
            raise PermissionResolutionError('source_revoked', 403)
        def capture_tool(self, *args): pytest.fail('denied evidence must not be captured')
    monkeypatch.setattr('retrieval.reranker._load_model',
                        lambda *args: pytest.fail('denied evidence must not enter a model'))
    search = SearchTool(backend=Backend(), documents_dir=str(tmp_path))
    tool = SimpleNamespace(name='echo', parameters={},
        execute=lambda **kwargs: getattr(search, method)('Question', filters={'doc_ids': ['doc']}))
    token = CURRENT_ACCESS_GUARD.set(Guard())
    try:
        with pytest.raises(PermissionResolutionError, match='source_revoked'):
            execute(tool)
    finally:
        CURRENT_ACCESS_GUARD.reset(token)
    assert BEFORE_RERANK.get() is None


def test_personal_tool_preserves_source_denial(monkeypatch):
    from agent.service.permission_service import PermissionResolutionError
    from tool_layer.search_library_tool import SearchLibraryTool

    def deny(payload): raise PermissionResolutionError('source_revoked', 403)
    monkeypatch.setattr('tool_layer.search_library_tool.search_library_evidence', deny)
    with pytest.raises(PermissionResolutionError, match='source_revoked'):
        SearchLibraryTool._post({})


def test_guard_context_and_prepared_arguments_reach_worker_before_capture():
    events = []

    class Guard:
        def prepare_tool(self, name, arguments):
            events.append("prepare")
            return {**arguments, "allowed_doc_ids": ["permitted"]}

        def capture_tool(self, name, data, evidence):
            events.append("capture")
            assert data == {"allowed_doc_ids": ["permitted"]}

    guard = Guard()

    def operation(**arguments):
        assert CURRENT_ACCESS_GUARD.get() is guard
        events.append("execute")
        return arguments

    tool = SimpleNamespace(name="echo", parameters={}, execute=operation)
    token = CURRENT_ACCESS_GUARD.set(guard)
    try:
        assert execute(tool).success
        assert events == ["prepare", "execute", "capture"]
    finally:
        CURRENT_ACCESS_GUARD.reset(token)

    events.clear()
    tool.execute = lambda **kwargs: {"guard": CURRENT_ACCESS_GUARD.get()}
    assert execute(tool).data == {"guard": None}


def test_timeout_keeps_running_capacity_and_cancels_queued_work(monkeypatch):
    pool = _BoundedToolExecutor(max_workers=1, max_pending=1)
    monkeypatch.setattr(execution_pool, "_SHARED_TOOL_EXECUTOR", pool)
    entered, release, queued_ran = Event(), Event(), Event()

    def block():
        entered.set()
        assert release.wait(5)

    # A timed-out running task still owns its slot. A queued timed-out task
    # must release its slot immediately and must never run later.
    try:
        with pytest.raises(FutureTimeout):
            execution_pool.run_with_timeout(block, timeout_ms=20)
        assert entered.wait(1)
        with pytest.raises(FutureTimeout):
            execution_pool.run_with_timeout(queued_ran.set, timeout_ms=20)
        queued = pool.submit(lambda: "queued")
        with pytest.raises(ToolCapacityExhausted):
            pool.submit(lambda: None)
        release.set()
        assert queued.result(timeout=1) == "queued"
        assert pool.submit(lambda: "recovered").result(timeout=1) == "recovered"
        assert not queued_ran.is_set()
    finally:
        release.set()
        pool._executor.shutdown(wait=True, cancel_futures=True)


def test_search_without_structured_method_retains_generic_fallback():
    tool = SimpleNamespace(
        name="search_documents", parameters={}, execute=lambda **arguments: "raw result",
    )
    result = execute(tool, query="query")
    assert result.success
    assert result.data == {"result": "raw result"}
    assert result.evidence == []
