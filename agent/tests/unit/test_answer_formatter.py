from agent.formatter.answer_formatter import AnswerFormatter
from agent.schemas.common import StatusCode
from agent.schemas.retrieval import RetrievalResult


def test_answer_formatter_generates_citations() -> None:
    result = RetrievalResult(
        doc_id="doc-1",
        chunk_id="chunk-1",
        chunk_text="abc" * 60,
        title="测试文档",
        source_url="https://example.local/doc-1",
        score=0.9,
    )

    response = AnswerFormatter().format_success("trace-test", "答案 [1]", [result])

    assert response.status == StatusCode.SUCCESS
    assert response.message == ""
    assert response.citations[0].citation_id == 1
    assert response.citations[0].doc_id == "doc-1"
    assert response.citations[0].snippet == result.chunk_text[:120]

