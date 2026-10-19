import json
import pytest
import sys
from types import ModuleType, SimpleNamespace
from pathlib import Path

# Add agent and project root folders to sys.path
agent_dir = Path(__file__).resolve().parent.parent
project_root = agent_dir.parent


@pytest.fixture(autouse=True)
def isolated_semantic_reranker(monkeypatch):
    monkeypatch.setenv('RERANK_ENABLED', 'false')
    from agent.config.settings import settings
    # Ordinary tests exercise production permissions even on a developer's machine.
    monkeypatch.setattr(settings, 'RESEARCH_DEVELOPMENT_MODE', False)

dependency_dirs = [
    agent_dir,
    project_root,
    project_root / "data-pipeline",
    project_root / "data-persistence",
    project_root / "toolset",
]
for dependency_dir in dependency_dirs:
    if str(dependency_dir) not in sys.path:
        sys.path.insert(0, str(dependency_dir))

# Persistence is optional for Agent unit tests. Provide an import-only fallback
# when pymilvus is not installed; retrieval calls remain explicitly mocked.
try:
    import pymilvus  # noqa: F401
except ModuleNotFoundError:
    pymilvus_stub = ModuleType("pymilvus")
    def unavailable_milvus(*args, **kwargs):
        raise RuntimeError("pymilvus is unavailable in this test environment")

    pymilvus_stub.connections = SimpleNamespace(
        connect=unavailable_milvus,
        disconnect=unavailable_milvus,
    )
    pymilvus_stub.utility = SimpleNamespace()
    pymilvus_stub.Collection = object
    pymilvus_stub.CollectionSchema = object
    pymilvus_stub.FieldSchema = object
    pymilvus_stub.DataType = SimpleNamespace()
    sys.modules["pymilvus"] = pymilvus_stub


@pytest.fixture(autouse=True)
def mock_llm_client_chat(monkeypatch):
    """Automatically mocks LLMClient.chat for all tests to keep them hermetic and mock-free in prod."""
    from agent.llm.llm_client import LLMClient
    from tests.grounding_helpers import grounded_model, grounded_content, control_response

    @grounded_model
    def mock_chat(self, messages, tools=None, **kwargs):
        # Simulate LLM tool calling and final response loop
        has_tool_response = any(msg.get("role") == "tool" or "[TOOL_OBSERVATIONS]" in str(msg.get("content", "")) for msg in messages)
        if tools and has_tool_response:
            return control_response("answer")

        if tools and not has_tool_response:
            user_query = ""
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    user_query = msg.get("content", "")
                    break
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_mock_123",
                        "type": "function",
                        "function": {
                            "name": "search_documents",
                            "arguments": json.dumps({"query": user_query})
                        }
                    }
                ]
            }

        return {
            "role": "assistant",
            "content": (
                "The retrieved documents describe these requirements:\n"
                "[1] This is the first document passage.\n"
                "[2] This is the second test explanation passage.\n"
                "These passages describe the project requirements."
            )
        }

    def mock_stream_chat(self, messages, tools=None, **kwargs):
        yield {"reasoning_content": "Reviewing the retrieved knowledge-base evidence..."}
        yield {"content": grounded_content("The retrieved documents describe these requirements:\n[1] This is the first document passage.\n[2] This is the second test explanation passage.\nThese passages describe the project requirements.", messages)}

    monkeypatch.setattr(LLMClient, "chat", mock_chat)
    monkeypatch.setattr(LLMClient, "stream_chat", mock_stream_chat)


@pytest.fixture(autouse=True)
def mock_search_tool(monkeypatch):
    """Keep Agent tests independent of the optional local embedding runtime."""
    from toolset.tool_layer.search_tool import SearchTool

    def mock_search(
        self,
        query,
        top_k=5,
        mode="hybrid",
        filters=None,
        min_score=0.0,
        trace_id=None,
    ):
        return [
            {
                "doc_id": "doc-001",
                "chunk_id": "doc-001::chunk_0",
                "chunk_index": 0,
                "chunk_text": "This is the first document passage.",
                "title": "Test Document One",
                "source_url": "https://example.com/doc-001",
                "score": 0.92,
            },
            {
                "doc_id": "doc-002",
                "chunk_id": "doc-002::chunk_0",
                "chunk_index": 0,
                "chunk_text": "This is the second test explanation passage.",
                "title": "Test Document Two",
                "source_url": "https://example.com/doc-002",
                "score": 0.88,
            },
        ][:top_k]

    monkeypatch.setattr(SearchTool, "search", mock_search)
    # Most Agent tests replace the retrieval boundary; Toolset tests exercise
    # the real direct primitive separately. Respect per-test search transports.
    monkeypatch.setattr(SearchTool, "search_direct", lambda self, **kwargs: self.search(**kwargs))


@pytest.fixture(autouse=True)
def mock_sqlite_db_path(monkeypatch, tmp_path, request):
    """Redirects the SQLite database to a temporary location for tests to ensure cleanliness."""
    if request.node.get_closest_marker("no_storage"):
        return

    from data_persistence.chat import ChatHistoryStore
    db_file = tmp_path / "test_chat_history.db"
    
    # Override initializer to use our temporary test database path
    original_init = ChatHistoryStore.__init__
    def patched_init(self, db_path=None):
        original_init(self, db_path=str(db_file))
        
    monkeypatch.setattr(ChatHistoryStore, "__init__", patched_init)


@pytest.fixture(autouse=True)
def mock_agent_auth(monkeypatch, request):
    """General HTTP tests use a BFF credential; dedicated auth tests exercise rejection."""
    if request.module.__name__.endswith("test_auth"):
        return
    from fastapi.testclient import TestClient
    from agent.config.settings import settings
    monkeypatch.setattr(settings, "AGENT_API_KEY", "integration-test-key")
    original_init = TestClient.__init__
    def authenticated_init(self, *args, **kwargs):
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("Authorization", "Bearer integration-test-key")
        original_init(self, *args, headers=headers, **kwargs)
    monkeypatch.setattr(TestClient, "__init__", authenticated_init)


# These historical tests exercise orchestration/quality/memory components with
# invented tool output, not source authorization. Keep that test double explicit
# and return incomplete provenance: they must NEVER count as security acceptance.
# Strict HTTP/source tests (including *_security.py) do not use this fixture.
_COMPONENT_SUITES = {
    "test_agent", "test_fast_stream_integration", "test_memory_observability",
    "test_chat_research_boundary", "test_cp2_memory_flow", "test_cp2_orchestration",
    "test_error_cases", "test_mock_agent_chain", "test_persistent_memory",
    "test_tool_layer_smoke", "test_week4_web_contract",
    "test_internal_memory_api", "test_internal_memory_routes",
    "test_agent_exploration_contract",
}


@pytest.fixture(autouse=True)
def component_authorization_double(monkeypatch, request):
    if request.module.__name__.rsplit(".", 1)[-1] not in _COMPONENT_SUITES:
        return
    import agent.agent as module
    from agent.schemas.chat import EvidenceProvenance
    from agent.service.permission_service import PermissionService

    class ComponentGuard:
        def __init__(self, permissions, request, trace_id):
            self.request, self.trace_id = request, trace_id
        def sanitize_request(self): return self.request
        def check_dependencies(self): pass
        def capture_tool(self, *args): pass
        def prepare_tool(self, name, arguments): return arguments
        def _inherit_if_allowed(self, dependencies): return True
        def provenance(self):
            return EvidenceProvenance(complete=False, trace_id=self.trace_id)

    class UnenforcedComponentContext:
        def get(self): return None
        def set(self, value): return None
        def reset(self, token): pass

    def component_filters(self, request):
        filters = dict(request.filters or {})
        if not request.user_id: return filters or None
        accessible = self.permission_service.get_accessible_doc_ids(request.user_id)
        if accessible is None: return filters or None
        ids = set(accessible)
        existing = filters.get("doc_ids", filters.get("doc_id"))
        if existing is not None: ids &= {existing} if isinstance(existing, str) else set(existing)
        filters.pop("doc_id", None)
        filters["doc_ids"] = sorted(ids)
        return filters

    from agent.evidence.gate import EvidenceGate, SupportCheck
    # These component fixtures exercise transport and Memory, not the classifier.
    monkeypatch.setattr(EvidenceGate, "evaluate", lambda self, binding, evidence, **kwargs:
        SupportCheck(True, [{"claim_id": c["claim_id"], "verdict": "supported"} for c in binding["claims"]]))
    monkeypatch.setattr(module, "AccessGuard", ComponentGuard)
    monkeypatch.setattr(module, "CURRENT_ACCESS_GUARD", UnenforcedComponentContext())
    monkeypatch.setattr(module.Agent, "_resolve_filters", component_filters)
    # Streaming transport preflight still invokes the permission resolver. This
    # component double has no real documents or authority and returns no grants.
    monkeypatch.setattr(PermissionService, 'get_accessible_doc_ids_strict', lambda self, user_id, doc_ids=None: [])
    # Transport fixtures remain service-token protected but now carry the
    # synthetic actor in the same header as the real BFF.
    from fastapi.testclient import TestClient
    original_request = TestClient.request
    def component_request(self, method, url, **kwargs):
        if str(url).startswith("/api/internal/"):
            body = kwargs.get("json") or {}
            for record in [*body.get("messages", []), *([body["active_snapshot"]] if body.get("active_snapshot") else [])]:
                record.setdefault("provenance_complete", True)
                record.setdefault("source_dependencies", [])
            actor = (body.get("memory_context") or {}).get("actor") or body.get("actor") or {}
            headers = dict(kwargs.get("headers") or {})
            headers.setdefault("X-User-ID", body.get("user_id") or actor.get("user_id") or "user-1")
            kwargs["headers"] = headers
        return original_request(self, method, url, **kwargs)
    monkeypatch.setattr(TestClient, "request", component_request)
    if request.module.__name__.rsplit(".", 1)[-1] in {"test_internal_memory_api", "test_internal_memory_routes"}:
        from agent.api import internal_memory_routes
        monkeypatch.setattr(internal_memory_routes, "resolve_access", lambda *args, **kwargs: [])
        monkeypatch.setattr(internal_memory_routes, "AccessGuard", ComponentGuard)


@pytest.fixture
def research_documents_dir(tmp_path: Path) -> Path:
    """Minimal local sources for report, conflict and crash-recovery regressions."""
    directory = tmp_path / "research-documents"
    directory.mkdir()
    documents = [{'doc_id': 'budget-a', 'title': '预算版本 A', 'version': 'v1', 'content': '2026 年度预算为 100 万元。'},
     {'doc_id': 'budget-b', 'title': '预算版本 B', 'version': 'v1', 'content': '2026 年度预算为 120 万元。'},
     {'doc_id': 'incomplete-metrics',
      'title': '经营指标摘录',
      'version': 'v1',
      'content': '资料仅记录收入为 100 万元。\n其他指标未收录。'},
     {'doc_id': 'project-alpha',
      'title': '项目 Alpha 状态',
      'version': 'v1',
      'content': '项目 Alpha 的部署状态为已完成。\n部署验收记录已归档。'},
     {'doc_id': 'project-beta',
      'title': '项目 Beta 状态',
      'version': 'v1',
      'content': '项目 Beta 的部署状态为已完成。\n部署验收记录已归档。'}]
    for document in documents:
        (directory / f"{document['doc_id']}.json").write_text(
            json.dumps(document, ensure_ascii=False), encoding="utf-8",
        )
    return directory
