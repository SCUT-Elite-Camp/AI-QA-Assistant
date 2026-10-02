# agent/errors/exceptions.py

"""Custom exception definitions."""


class AgentError(Exception):
    """Base exception for Agent Layer."""
    pass


class LLMError(AgentError):
    """Raised when LLM invocation fails."""
    pass
