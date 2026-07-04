# agent/errors/exceptions.py

"""Custom exception definitions."""


class AgentError(Exception):
    """Base exception for Agent Layer."""

    pass


class RetrievalError(AgentError):
    """Base exception for retrieval-related errors."""

    pass


class RetrievalTimeoutError(RetrievalError):
    """Raised when retrieval times out."""

    pass


class RetrievalEmptyError(RetrievalError):
    """Raised when retrieval returns no usable results."""

    pass


class RetrievalResultFormatError(RetrievalError):
    """Raised when retrieval result format is invalid."""

    pass


class LLMError(AgentError):
    """Raised when LLM invocation fails."""

    pass


class InvalidQueryError(AgentError):
    """Raised when the input query is invalid."""

    pass


class NoRelevantContextError(AgentError):
    """Raised when no relevant context is available."""

    pass


class ConfigError(AgentError):
    """Raised when configuration is invalid."""

    pass