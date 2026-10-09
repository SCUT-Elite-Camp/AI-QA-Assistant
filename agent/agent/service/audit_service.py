import logging
import time
from agent.logger.app_logger import log_chat_result

logger = logging.getLogger("agent-layer")


class AuditService:
    """Service for request timing and structured operational logging."""

    def start_timer(self) -> float:
        """Starts timing request latency."""
        return time.perf_counter()

    def stop_timer(self, start_time: float) -> int:
        """Stops timing request latency and returns the duration in milliseconds."""
        return int((time.perf_counter() - start_time) * 1000)

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
