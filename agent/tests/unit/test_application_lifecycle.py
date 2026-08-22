from agent.agent import Agent
from agent.llm.base import BaseLLM
from agent.runtime.lifecycle import ApplicationContainer
from toolset.tool_layer.base_tool import BaseTool
from toolset.tool_layer.registry import ToolRegistry


class StubLLM(BaseLLM):
    def generate(self, prompt: str) -> str:
        return "stub"

    def chat(self, messages: list[dict], tools: list[dict] = None) -> dict:
        return {"role": "assistant", "content": "stub"}


class StubSearchTool(BaseTool):
    @property
    def name(self) -> str:
        return "search_documents"

    @property
    def description(self) -> str:
        return "stub search"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs):
        return []

    def search(self, **kwargs):
        return []


def test_application_container_reuses_agent_llm_registry_and_tool() -> None:
    llm = StubLLM()
    tool = StubSearchTool()
    registry = ToolRegistry(tools=[tool])
    container = ApplicationContainer(
        llm_factory=lambda: llm,
        registry_factory=lambda: registry,
    )

    first = container.get_agent()
    second = container.get_agent()

    assert isinstance(first, Agent)
    assert first is second
    assert first.llm is llm
    assert first.registry._registry is registry
    assert first.registry.get_tool("search_documents") is tool
    assert container.snapshot().initialization_count == 1


def test_warmup_uses_the_shared_search_tool() -> None:
    tool = StubSearchTool()
    calls: list[dict] = []
    tool.search = lambda **kwargs: calls.append(kwargs) or []  # type: ignore[method-assign]
    container = ApplicationContainer(
        llm_factory=StubLLM,
        registry_factory=lambda: ToolRegistry(tools=[tool]),
    )

    agent = container.get_agent()
    container.warmup_retrieval()

    assert agent.registry.get_tool("search_documents") is tool
    assert len(calls) == 1
    assert calls[0]["trace_id"] == "startup-preload"
    assert container.snapshot().retrieval_ready is True

