from agent.schemas.common import StatusCode


def test_status_codes_are_defined() -> None:
    assert StatusCode.SUCCESS == "success"
    assert StatusCode.INVALID_QUERY == "invalid_query"
    assert StatusCode.NO_RELEVANT_CONTEXT == "no_relevant_context"
    assert StatusCode.RETRIEVAL_ERROR == "retrieval_error"
    assert StatusCode.LLM_ERROR == "llm_error"

