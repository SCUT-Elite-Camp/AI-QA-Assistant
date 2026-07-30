from enum import StrEnum

class StatusCode(StrEnum):
    SUCCESS = "success"
    CLARIFICATION_REQUIRED = "clarification_required"
    AGENT_LIMIT_REACHED = "agent_limit_reached"
    TOOL_ERROR = "tool_error"
    INVALID_QUERY = "invalid_query"
    NO_RELEVANT_CONTEXT = "no_relevant_context"
    RETRIEVAL_ERROR = "retrieval_error"
    LLM_ERROR = "llm_error"

