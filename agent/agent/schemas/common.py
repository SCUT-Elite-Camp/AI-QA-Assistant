from enum import StrEnum

class StatusCode(StrEnum):
    SUCCESS = "success"
    INVALID_QUERY = "invalid_query"
    NO_RELEVANT_CONTEXT = "no_relevant_context"
    RETRIEVAL_ERROR = "retrieval_error"
    LLM_ERROR = "llm_error"

