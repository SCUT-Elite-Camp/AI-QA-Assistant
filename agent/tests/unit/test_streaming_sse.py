from agent.schemas.chat import ChatRequest, ChatResponse, Citation
from agent.streaming.sse import chat_response_events
from agent.agent import Agent


def test_chat_response_events_preserve_response_and_chunk_answer() -> None:
    response = ChatResponse(
        trace_id="trace-1",
        status="success",
        answer="甲" * 70,
        message="",
        citations=[
            Citation(
                citation_id=1,
                title="Example",
                doc_id="doc-1",
                chunk_id="chunk-1",
                score=0.9,
                snippet="evidence",
            )
        ],
        chat_title="Example chat",
    )

    events = list(chat_response_events(response))

    assert [name for name, _ in events] == ["citations", "token", "token", "token", "done"]
    assert events[0][1] == [response.citations[0].model_dump()]
    assert "".join(data["content"] for name, data in events if name == "token") == response.answer
    assert all(len(data["content"]) <= 32 for name, data in events if name == "token")
    assert events[-1][1] == {
        "trace_id": "trace-1",
        "status": "success",
        "citations_count": 1,
        "chat_title": "Example chat",
    }


def test_chat_response_events_emit_error_for_non_success() -> None:
    response = ChatResponse(
        trace_id="trace-2",
        status="invalid_query",
        answer="",
        message="请输入有效问题。",
        citations=[],
    )

    assert list(chat_response_events(response)) == [
        ("citations", []),
        ("error", {"message": "请输入有效问题。"}),
    ]


def test_agent_stream_chat_delegates_to_canonical_chat(monkeypatch) -> None:
    agent = Agent()
    response = ChatResponse(
        trace_id="trace-3",
        status="success",
        answer="canonical answer",
        message="",
        citations=[],
    )
    calls = []

    def fake_chat(request):
        calls.append(request)
        return response

    monkeypatch.setattr(agent, "chat", fake_chat)

    events = list(agent.stream_chat(ChatRequest(query="question", weight_mode="fast")))

    assert len(calls) == 1
    assert calls[0].weight_mode == "fast"
    assert events == list(chat_response_events(response))
