from typing import Optional
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from agent.schemas.chat import ChatRequest, ChatResponse, Citation
from agent.agent import Agent
from agent.auth import verify_agent_key
from agent.config.settings import settings
from agent.streaming.sse import build_sse_event

router = APIRouter()


_agent_instance: Optional[Agent] = None


def get_agent() -> Agent:
    """Dependency provider for Agent (singleton instance)."""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = Agent()
    return _agent_instance


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
    def event_stream():
        for event_name, event_data in agent.stream_chat(request):
            yield build_sse_event(event_name, event_data)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
        existing_info=req.existing_info,
    )
    return result

