from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any

AGENT_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = AGENT_DIR.parent
for folder in (AGENT_DIR, PROJECT_ROOT, PROJECT_ROOT / "toolset", PROJECT_ROOT / "data-persistence"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from agent.agent import Agent
from agent.llm.base import BaseLLM
from agent.schemas.chat import ChatRequest
from agent.schemas.query_plan import QueryPlan
from toolset.tool_layer.base_tool import BaseTool


class TimedFakeLLM(BaseLLM):
    def __init__(self) -> None:
        self.call_count = 0
        self.durations_ms: list[float] = []

    def generate(self, prompt: str) -> str:
        return self.chat([{"role": "user", "content": prompt}])["content"]

    def chat(self, messages: list[dict], tools: list[dict] = None, **kwargs) -> dict:
        started = time.perf_counter()
        self.call_count += 1
        try:
            has_tool_result = any(message.get("role") == "tool" for message in messages)
            if tools and not has_tool_result:
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": f"baseline-tool-{self.call_count}",
                        "type": "function",
                        "function": {
                            "name": "search_documents",
                            "arguments": json.dumps({"query": "CP2 Agent lifecycle", "top_k": 2}),
                        },
                    }],
                }
            return {
                "role": "assistant",
                "content": "应用级资源在生命周期内复用，并保留请求级证据。[1]",
            }
        finally:
            self.durations_ms.append((time.perf_counter() - started) * 1000)


class TimedFakeSearchTool(BaseTool):
    def __init__(self) -> None:
        self.call_count = 0
        self.durations_ms: list[float] = []
        self.min_score = 0.0

    @property
    def name(self) -> str:
        return "search_documents"

    @property
    def description(self) -> str:
        return "Deterministic baseline search tool"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
        }

    def execute(self, **kwargs: Any) -> Any:
        return self.search(**kwargs)

    def search(self, query: str, top_k: int = 5, **kwargs: Any) -> list[dict]:
        started = time.perf_counter()
        self.call_count += 1
        try:
            return [{
                "doc_id": "baseline-doc",
                "chunk_id": "baseline-doc::chunk-0",
                "chunk_index": 0,
                "chunk_text": "Agent、LLM Client、Tool Registry 和 Search Tool 应按应用生命周期复用。",
                "title": "CP2 Week 1 Baseline",
                "source_url": "local://cp2/week1",
                "score": 0.99,
            }][:top_k]
        finally:
            self.durations_ms.append((time.perf_counter() - started) * 1000)


class NoOpAuditService:
    @staticmethod
    def start_timer() -> float:
        return time.perf_counter()

    @staticmethod
    def stop_timer(start_time: float) -> int:
        return int((time.perf_counter() - start_time) * 1000)

    @staticmethod
    def record(**kwargs: Any) -> None:
        return None

    @staticmethod
    def log_step(step: int, query: str) -> None:
        return None

    @staticmethod
    def log_tool_call(name: str, args: dict) -> None:
        return None

    @staticmethod
    def log_result(**kwargs: Any) -> None:
        return None


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def _summary(values: list[float]) -> dict[str, float | int]:
    return {
        "count": len(values),
        "mean_ms": round(statistics.fmean(values), 4),
        "p50_ms": round(_percentile(values, 0.50), 4),
        "p95_ms": round(_percentile(values, 0.95), 4),
        "min_ms": round(min(values), 4),
        "max_ms": round(max(values), 4),
    }


def run(iterations: int) -> dict[str, Any]:
    llm = TimedFakeLLM()
    search = TimedFakeSearchTool()
    started = time.perf_counter()
    agent = Agent(llm=llm, tools=[search], audit_service=NoOpAuditService())  # type: ignore[arg-type]
    initialization_ms = (time.perf_counter() - started) * 1000
    request = ChatRequest(
        query="CP2 Week 1 为什么需要复用应用资源？",
        session_id=None,
    )
    plan = QueryPlan(original_query=request.query, standalone_query=request.query)
    request_latencies: list[float] = []
    per_request: list[dict[str, int | float | str]] = []

    for index in range(iterations):
        llm_before = llm.call_count
        tool_before = search.call_count
        request_started = time.perf_counter()
        response = agent.chat(request, query_plan=plan)
        elapsed_ms = (time.perf_counter() - request_started) * 1000
        request_latencies.append(elapsed_ms)
        per_request.append({
            "iteration": index + 1,
            "status": str(response.status),
            "latency_ms": round(elapsed_ms, 4),
            "llm_calls": llm.call_count - llm_before,
            "tool_calls": search.call_count - tool_before,
        })

    return {
        "schema_version": "1.0",
        "benchmark": "chat_mock_lifecycle_baseline",
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "fastapi": version("fastapi"),
            "pydantic": version("pydantic"),
            "pytest": version("pytest"),
        },
        "iterations": iterations,
        "initialization_ms": round(initialization_ms, 4),
        "request_latency": _summary(request_latencies),
        "llm_stage": {
            **_summary(llm.durations_ms),
            "total_calls": llm.call_count,
            "calls_per_request": llm.call_count / iterations,
        },
        "tool_stage": {
            **_summary(search.durations_ms),
            "total_calls": search.call_count,
            "calls_per_request": search.call_count / iterations,
        },
        "resource_identity": {
            "agent_id": id(agent),
            "llm_id": id(agent.llm),
            "registry_id": id(agent.registry._registry),
            "search_tool_id": id(agent.registry.get_tool("search_documents")),
        },
        "requests": per_request,
        "notes": [
            "Deterministic Mock LLM and local in-memory search are used.",
            "Numbers are a reproducible lifecycle baseline, not production latency.",
            "No external LLM, Milvus, or network service is required.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 20 <= args.iterations <= 50:
        parser.error("--iterations must be between 20 and 50")
    result = run(args.iterations)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

