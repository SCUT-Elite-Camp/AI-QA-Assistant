import json
import pytest
import sys
from types import ModuleType, SimpleNamespace
from pathlib import Path

# Add agent and project root folders to sys.path
agent_dir = Path(__file__).resolve().parent.parent
project_root = agent_dir.parent

if str(agent_dir) not in sys.path:
    sys.path.insert(0, str(agent_dir))
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Persistence is optional for Agent unit tests. Provide an import-only fallback
# when pymilvus is not installed; retrieval calls remain explicitly mocked.
try:
    import pymilvus  # noqa: F401
except ModuleNotFoundError:
    pymilvus_stub = ModuleType("pymilvus")
    pymilvus_stub.connections = SimpleNamespace()
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

    def mock_chat(self, messages, tools=None):
        # Simulate LLM tool calling and final response loop
        has_tool_response = any(msg.get("role") == "tool" for msg in messages)

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
                "根据检索到的文档，我们发现以下规则：\n"
                "[1] 这是第一个文档段落。\n"
                "[2] 这是第二个测试说明段落。\n"
                "这些文档非常清晰地展示了项目要求。"
            )
        }

    monkeypatch.setattr(LLMClient, "chat", mock_chat)


@pytest.fixture(autouse=True)
def mock_sqlite_db_path(monkeypatch, tmp_path, request):
    """Redirects the SQLite database to a temporary location for tests to ensure cleanliness."""
    if request.node.get_closest_marker("no_storage"):
        return

    from storage.chat_history_store import ChatHistoryStore
    db_file = tmp_path / "test_chat_history.db"
    
    # Override initializer to use our temporary test database path
    original_init = ChatHistoryStore.__init__
    def patched_init(self, db_path=None):
        original_init(self, db_path=str(db_file))
        
    monkeypatch.setattr(ChatHistoryStore, "__init__", patched_init)

