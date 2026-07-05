# agent/errors/exceptions.py

"""Custom exception definitions."""


class AgentError(Exception):
    """Base exception for Agent Layer."""
    pass


class RetrievalError(AgentError):
    """Base exception for retrieval-related errors."""
    pass


class LLMError(AgentError):
    """Raised when LLM invocation fails."""
    pass