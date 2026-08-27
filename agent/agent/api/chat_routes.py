from typing import Optional
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from agent.schemas.chat import ChatRequest, ChatResponse
from agent.agent import Agent
from agent.auth import verify_agent_key
from agent.config.settings import settings
from agent.streaming.sse import build_sse_event

router = APIRouter()


def get_agent() -> Agent:
    """Dependency provider for Agent."""
    return Agent()


@router.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    agent: Agent = Depends(get_agent),
    _: None = Depends(verify_agent_key),
) -> ChatResponse:
    return agent.chat(request)


@router.get("/chat/history")
def chat_history(
    limit: int = 50,
    agent: Agent = Depends(get_agent),
    _: None = Depends(verify_agent_key),
) -> list[dict]:
    return agent.get_history(limit)


@router.delete("/chat/memory/{session_id}")
def clear_chat_memory(
    session_id: str,
    agent: Agent = Depends(get_agent),
    _: None = Depends(verify_agent_key),
) -> dict[str, str]:
    """Clears conversation memory for the given session_id."""
    agent.memory.clear(session_id)
    return {"status": "ok", "session_id": session_id}



@router.get("/tools")
def list_available_tools(
    agent: Agent = Depends(get_agent),
    _: None = Depends(verify_agent_key),
) -> list[dict]:
    """Returns public metadata for all tools registered with the Agent."""
    return agent.registry.list_tool_metadata()

@router.post("/chat/stream")
def chat_stream(
    request: ChatRequest,
    agent: Agent = Depends(get_agent),
    _: None = Depends(verify_agent_key),
) -> StreamingResponse:
    response = agent.chat(request)

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
                "chat_title": response.chat_title,
            },
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _chunk_answer(answer: str, chunk_size: int = 24) -> list[str]:
    return [answer[index:index + chunk_size] for index in range(0, len(answer), chunk_size)]


from pydantic import BaseModel
from services.summarizer.topic_summarizer import TopicSummarizer

class SummarizeTopicRequest(BaseModel):
    topic_id: str
    discussion_text: str
    custom_title: Optional[str] = None
    existing_info: Optional[dict] = None

@router.post("/topics/summarize")
def summarize_topic(
    req: SummarizeTopicRequest,
    _: None = Depends(verify_agent_key),
):
    """
    Triggers Data Persistence Layer Summarizer Service.
    Generates Title, Description, Soul Cognition (Soul.md), and Content Tags,
    and directly writes artifacts into data-persistence/data/topics/<topic_id>/
    """
    result = TopicSummarizer.summarize_and_persist(
        topic_id=req.topic_id,
        discussion_text=req.discussion_text,
        custom_title=req.custom_title,
        existing_info=req.existing_info
    )
    return result

