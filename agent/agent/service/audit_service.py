import logging
import time
from storage.chat_history_store import ChatHistoryStore
from agent.logger.app_logger import log_chat_result

logger = logging.getLogger("agent-layer")


class AuditService:
    """Service for timing query latency, recording chat outcomes to SQLite, and logging steps."""

    def __init__(self) -> None:
        self.store = ChatHistoryStore()

    def start_timer(self) -> float:
        """Starts timing request latency."""
        return time.perf_counter()

    def stop_timer(self, start_time: float) -> int:
        """Stops timing request latency and returns the duration in milliseconds."""
        return int((time.perf_counter() - start_time) * 1000)

    def record(
        self,
        trace_id: str,
        query: str,
        answer: str,
        status: str,
        latency_ms: int,
        session_id: str = None
    ) -> None:
        """Saves audit record to SQLite database."""
        try:
            self.store.add_record(
                trace_id=trace_id,
                session_id=session_id,
                user_query=query,
                assistant_answer=answer,
                status=status,
                latency_ms=latency_ms,
            )
        except Exception as e:
            logger.error(f"Failed to save audit history: {e}")

    def log_step(self, step: int, query: str) -> None:
        """Logs each step iteration of the Agent loop."""
        logger.info(f"Agent loop iteration {step + 1} starting for query: {query}")

    def log_tool_call(self, name: str, args: dict) -> None:
        """Logs tool invocation by the Agent."""
        logger.info(f"Agent executing tool '{name}' with arguments: {args}")

    def log_result(
        self,
        trace_id: str,
        query: str,
        retrieval_count: int,
        status: str,
        stage: str = "completed",
        retrieval_mode: str = "hybrid",
        top_k: int = 5,
        error: str = ""
    ) -> None:
        """Logs overall query result audit."""
        log_chat_result(
            trace_id=trace_id,
            query=query,
            retrieval_count=retrieval_count,
            status=status,
            stage=stage,
            retrieval_mode=retrieval_mode,
            top_k=top_k,
            error=error,
        )
