import os
import tempfile
from typing import Any

from agent.agent import Agent
from agent.memory import InMemoryConversationMemory
from agent.schemas.chat import ChatRequest
from agent.schemas.common import StatusCode
from storage.chat_history_store import ChatHistoryStore


class DummyLLM:
    def generate(self, prompt: str) -> str:
        return prompt

    def chat(self, messages: list[dict], tools=None) -> dict:
        return {"role": "assistant", "content": "Persisted response"}


def test_persistent_memory_restores_from_data_persistence() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_persistent.db")
        store = ChatHistoryStore(db_path=db_path)

        # 1. First turn with agent_1
        memory_1 = InMemoryConversationMemory()
        agent_1 = Agent(llm=DummyLLM(), tools=[], memory=memory_1)
        agent_1.audit_service.store = store

        session_id = "persistent-session-999"
        res_1 = agent_1.chat(ChatRequest(query="First turn query", session_id=session_id))
        assert res_1.status == StatusCode.SUCCESS

        # Verify DB has recorded this turn
        records = store.get_session_records(session_id)
        assert len(records) == 1
        assert records[0]["user_query"] == "First turn query"

        # 2. Simulate process restart by instantiating agent_2 with clean memory
        memory_2 = InMemoryConversationMemory()
        agent_2 = Agent(llm=DummyLLM(), tools=[], memory=memory_2)
        agent_2.audit_service.store = store

        # memory_2 initially has no session in RAM
        assert "persistent-session-999" not in memory_2._sessions

        # get_messages should trigger fallback to ChatHistoryStore in data-persistence
        recovered_messages = memory_2.get_messages(session_id)
        assert len(recovered_messages) == 2
        assert recovered_messages[0] == {"role": "user", "content": "First turn query"}

        # 3. Clear memory via agent_2 should clear both RAM and persistent storage in DB
        agent_2.memory.clear(session_id)
        assert memory_2.get_messages(session_id) == []
        assert store.get_session_records(session_id) == []
