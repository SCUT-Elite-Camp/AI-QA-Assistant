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


def test_answer_formatter_adds_reference_when_missing() -> None:
    result = RetrievalResult(
        doc_id="doc-1",
        chunk_id="chunk-1",
        chunk_text="测试上下文",
        title="测试文档",
        source_url="",
        score=0.9,
    )

    response = AnswerFormatter().format_success("trace-test", "答案内容", [result])

    assert response.answer == "答案内容 [1]"


def test_answer_formatter_removes_invalid_reference() -> None:
    result = RetrievalResult(
        doc_id="doc-1",
        chunk_id="chunk-1",
        chunk_text="测试上下文",
        title="测试文档",
        source_url="",
        score=0.9,
    )

    response = AnswerFormatter().format_success("trace-test", "答案内容 [9]", [result])

    assert response.answer == "答案内容 [1]"
