import sqlite3
import os
from datetime import datetime, timezone
from pathlib import Path

# Resolve path relative to storage directory
DB_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DB_DIR / "chat_history.db"


class ChatHistoryStore:
    """Manages SQLite database for storing chat history and audit logs."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initializes the database schema if the table does not exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL UNIQUE,
                    session_id TEXT,
                    user_query TEXT NOT NULL,
                    assistant_answer TEXT,
                    status TEXT NOT NULL,
                    latency_ms INTEGER,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.commit()

    def add_record(
        self,
        trace_id: str,
        user_query: str,
        assistant_answer: str,
        status: str,
        latency_ms: int,
        session_id: str = None,
        timestamp: str = None
    ) -> None:
        """Adds a new chat query-response record to the audit log."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO chat_history 
                (trace_id, session_id, user_query, assistant_answer, status, latency_ms, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (trace_id, session_id, user_query, assistant_answer, status, latency_ms, timestamp)
            )
            conn.commit()

    def get_records(self, limit: int = 50) -> list[dict]:
        """Retrieves the latest chat history records up to the limit."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM chat_history ORDER BY id DESC LIMIT ?",
                (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_session_records(self, session_id: str, limit: int = 50) -> list[dict]:
        """Retrieves history records for a specific session_id."""
        if not session_id:
            return []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM chat_history WHERE session_id = ? ORDER BY id ASC LIMIT ?",
                (session_id, limit)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_session_messages(self, session_id: str, limit: int = 10) -> list[dict[str, str]]:
        """Extracts alternating user and assistant message dicts for short-term memory recovery."""
        records = self.get_session_records(session_id, limit=limit)
        messages: list[dict[str, str]] = []
        for record in records:
            if record.get("user_query"):
                messages.append({"role": "user", "content": record["user_query"]})
            if record.get("assistant_answer"):
                messages.append({"role": "assistant", "content": record["assistant_answer"]})
        return messages

    def clear_session(self, session_id: str) -> None:
        """Deletes all persistent chat records associated with session_id."""
        if not session_id:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM chat_history WHERE session_id = ?", (session_id,))
            conn.commit()

