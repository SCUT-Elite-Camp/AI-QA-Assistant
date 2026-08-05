import os
import tempfile
from storage.chat_history_store import ChatHistoryStore


def test_chat_history_store_session_records_and_clearing() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_chat.db")
        store = ChatHistoryStore(db_path=db_path)

        # 1. Add records for session-1 and session-2
        store.add_record(
            trace_id="t-1",
            user_query="Hello",
            assistant_answer="Hi!",
            status="success",
            latency_ms=100,
            session_id="session-1",
        )
        store.add_record(
            trace_id="t-2",
            user_query="How are you?",
            assistant_answer="Doing great!",
            status="success",
            latency_ms=120,
            session_id="session-1",
        )
        store.add_record(
            trace_id="t-3",
            user_query="Other session query",
            assistant_answer="Other answer",
            status="success",
            latency_ms=90,
            session_id="session-2",
        )

        # 2. Verify get_session_records & get_session_messages
        s1_records = store.get_session_records("session-1")
        assert len(s1_records) == 2
        assert s1_records[0]["user_query"] == "Hello"

        s1_messages = store.get_session_messages("session-1")
        assert len(s1_messages) == 4
        assert s1_messages[0] == {"role": "user", "content": "Hello"}
        assert s1_messages[1] == {"role": "assistant", "content": "Hi!"}
        assert s1_messages[2] == {"role": "user", "content": "How are you?"}
        assert s1_messages[3] == {"role": "assistant", "content": "Doing great!"}

        # 3. Verify clear_session
        store.clear_session("session-1")
        assert store.get_session_messages("session-1") == []
        assert len(store.get_session_records("session-2")) == 1
