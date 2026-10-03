from typing import Any

from agent.tools.executor import ToolExecutor
from toolset.tool_layer.base_tool import BaseTool


class _LibraryTool(BaseTool):
    @property
    def name(self) -> str:
        return "search_library"

    @property
    def description(self) -> str:
        return "test"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}

    def execute(self, **_: Any) -> dict[str, Any]:
        return {"items": [{
            "evidence_id": "ver-a_chunk_12",
            "knowledge_base_id": "kb-a",
            "document_id": "doc-a",
            "version_id": "ver-a",
            "source_scope": "personal",
            "filename": "risk.md",
            "content": "personal evidence",
            "score": 0.9,
            "locator": {"section_path": ["Architecture", "Retrieval"]},
        }]}


class _Registry:
    def get(self, name: str):
        return _LibraryTool() if name == "search_library" else None


def test_personal_evidence_keeps_stable_chunk_and_locator():
    result = ToolExecutor(_Registry()).execute(
        tool_call_id="call-1", tool_name="search_library",
        arguments={"query": "risk"}, trace_id="trace-1",
    )
    evidence = result.evidence[0]
    assert evidence.chunk_id == "ver-a_chunk_12"
    assert evidence.source_scope == "personal"
    assert evidence.document_id == "doc-a"
    assert evidence.version_id == "ver-a"
    assert evidence.locator == {"section_path": ["Architecture", "Retrieval"]}
