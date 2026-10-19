"""Request-local diagnostics remain isolated across concurrent calls."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from threading import Barrier
import pytest
from agent.agent import Agent

pytestmark = pytest.mark.no_storage


def test_agent_memory_and_diagnostics_are_request_local():
    agent = Agent.__new__(Agent)
    agent._last_run_result = ContextVar("runs", default=None)
    agent._last_orchestration = ContextVar("orchestrations", default=None)
    agent._last_citation_check = ContextVar("citations", default=None)
    barrier = Barrier(2)

    def call(value):
        agent.last_run_result = agent.last_orchestration = agent.last_citation_check = value
        barrier.wait(timeout=5)
        return agent.last_run_result, agent.last_orchestration, agent.last_citation_check

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(call, "alice"), pool.submit(call, "bob")
        assert a.result() == ("alice",) * 3
        assert b.result() == ("bob",) * 3
    assert agent.last_orchestration is None
