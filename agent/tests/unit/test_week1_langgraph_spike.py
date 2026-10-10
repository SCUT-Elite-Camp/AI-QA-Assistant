import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from deep_research.spikes.week1_langgraph import (
    SQLiteSpikeRuntime,
    build_spike_graph,
)


def test_three_nodes_interrupt_and_resume_with_replaceable_checkpointer() -> None:
    graph = build_spike_graph(InMemorySaver())
    config = {"configurable": {"thread_id": "research-memory"}}

    interrupted = graph.invoke(
        {"research_id": "research-memory", "steps": []},
        config,
    )
    assert "__interrupt__" in interrupted
    assert graph.get_state(config).values["steps"] == ["prepare"]

    from langgraph.types import Command

    completed = graph.invoke(Command(resume={"approved": True}), config)
    assert completed["approved"] is True
    assert completed["steps"] == ["prepare", "approval", "finalize"]
    json.dumps(dict(graph.get_state(config).values))


def test_sqlite_checkpoint_survives_runtime_restart(tmp_path) -> None:
    database = tmp_path / "checkpoint.sqlite"
    first = SQLiteSpikeRuntime(database)
    interrupted = first.start("research-restart")
    assert "__interrupt__" in interrupted
    first.close()

    second = SQLiteSpikeRuntime(database)
    try:
        snapshot = second.state("research-restart")
        assert snapshot.values["steps"] == ["prepare"]
        completed = second.approve("research-restart")
        assert completed["steps"] == ["prepare", "approval", "finalize"]
        assert second.state("research-restart").next == ()
    finally:
        second.close()


def test_node_failure_remains_at_latest_safe_checkpoint(tmp_path) -> None:
    database = tmp_path / "failure.sqlite"
    with SQLiteSpikeRuntime(database) as runtime:
        runtime.start("research-failure", fail_at="finalize")
        with pytest.raises(RuntimeError, match="injected finalize failure"):
            runtime.approve("research-failure")

        snapshot = runtime.state("research-failure")
        assert snapshot.values["steps"] == ["prepare", "approval"]
        assert snapshot.next == ("finalize",)

