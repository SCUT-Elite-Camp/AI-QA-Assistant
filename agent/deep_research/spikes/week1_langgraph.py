from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class SpikeState(TypedDict, total=False):
    """Serializable business state with no LangGraph base-class dependency."""

    research_id: str
    plan_version: int
    approved: bool
    steps: list[str]
    fail_at: str | None


def _prepare(state: SpikeState) -> SpikeState:
    return {
        "plan_version": 1,
        "steps": [*state.get("steps", []), "prepare"],
    }


def _approval(state: SpikeState) -> SpikeState:
    decision = interrupt(
        {
            "kind": "plan_approval",
            "research_id": state["research_id"],
            "plan_version": state["plan_version"],
        }
    )
    approved = bool(
        decision.get("approved", False)
        if isinstance(decision, dict)
        else decision
    )
    if not approved:
        raise ValueError("plan approval is required")
    return {
        "approved": True,
        "steps": [*state.get("steps", []), "approval"],
    }


def _finalize(state: SpikeState) -> SpikeState:
    if state.get("fail_at") == "finalize":
        raise RuntimeError("injected finalize failure")
    return {"steps": [*state.get("steps", []), "finalize"]}


def build_spike_graph(checkpointer: BaseCheckpointSaver):
    """Compile three deterministic nodes against any supported checkpointer."""
    builder = StateGraph(SpikeState)
    builder.add_node("prepare", _prepare)
    builder.add_node("approval", _approval)
    builder.add_node("finalize", _finalize)
    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "approval")
    builder.add_edge("approval", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer, name="week1-local-research-spike")


@dataclass
class SQLiteSpikeRuntime:
    """Small owner for the SQLite connection used by the Week 1 spike."""

    database_path: Path

    def __post_init__(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            str(self.database_path),
            check_same_thread=False,
        )
        self.checkpointer = SqliteSaver(self.connection)
        self.graph = build_spike_graph(self.checkpointer)

    @staticmethod
    def config(research_id: str) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": research_id}}

    def start(self, research_id: str, *, fail_at: str | None = None) -> dict[str, Any]:
        return self.graph.invoke(
            {
                "research_id": research_id,
                "steps": [],
                "approved": False,
                "fail_at": fail_at,
            },
            self.config(research_id),
        )

    def approve(self, research_id: str) -> dict[str, Any]:
        return self.graph.invoke(
            Command(resume={"approved": True}),
            self.config(research_id),
        )

    def state(self, research_id: str):
        return self.graph.get_state(self.config(research_id))

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "SQLiteSpikeRuntime":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

