from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from agent.schemas.chat import ChatRequest, ChatResponse
from agent.service.chat_service import ChatService
from agent.streaming.sse import build_sse_event

router = APIRouter()
chat_service = ChatService()


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    return chat_service.chat(request)


@router.post("/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    response = chat_service.chat(request)

    def event_stream():
        if response.answer:
            for token in _chunk_answer(response.answer):
                yield build_sse_event("token", {"content": token})

        yield build_sse_event(
            "citations",
            [citation.model_dump() for citation in response.citations],
        )
        yield build_sse_event(
            "done",
            {
                "trace_id": response.trace_id,
                "status": response.status,
                "message": response.message,
                "citations_count": len(response.citations),
            },
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _chunk_answer(answer: str, chunk_size: int = 24) -> list[str]:
    return [answer[index:index + chunk_size] for index in range(0, len(answer), chunk_size)]
