from agent.trace.trace_id import generate_trace_id, set_trace_id, clear_trace_id


class TraceService:
    """Service for managing request trace IDs and thread-local/ContextVar bindings."""

    def start_trace(self) -> str:
        """Generates and sets trace ID in thread context."""
        trace_id = generate_trace_id()
        set_trace_id(trace_id)
        return trace_id

    def clear_trace(self) -> None:
        """Cleans up trace ID from thread context."""
        clear_trace_id()
