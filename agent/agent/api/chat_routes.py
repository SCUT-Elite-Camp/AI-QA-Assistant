from typing import Iterator, Optional
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from agent.schemas.chat import ChatRequest, ChatResponse, Citation
from agent.agent import Agent
from agent.auth import verify_agent_key
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
from agent.llm.llm_client import LLMClient
from agent.service.topic_summarization_service import TopicSummarizationService
from data_persistence.topics import TopicArtifactRepository


class SummarizeTopicRequest(BaseModel):
    topic_id: str
    discussion_text: str
    custom_title: Optional[str] = None
    existing_info: Optional[dict] = None


class SummarizeTopicResponse(BaseModel):
    title: str
    description: Optional[str] = None
    soul_content: str
    tags: list[str]


def get_topic_summarization_service() -> Iterator[TopicSummarizationService]:
    """Build a request-scoped topic service using the current Agent settings."""
    llm = LLMClient(
        fallback_models=(),
        attempts_per_model=1,
        retry_delay_seconds=0,
    )
    try:
        yield TopicSummarizationService(
            llm=llm,
            repository=TopicArtifactRepository(),
        )
    finally:
        llm.close()


@router.post("/topics/summarize", response_model=SummarizeTopicResponse)
def summarize_topic(
    req: SummarizeTopicRequest,
    _: None = Depends(verify_agent_key),
    service: TopicSummarizationService = Depends(get_topic_summarization_service),
) -> SummarizeTopicResponse:
    """Summarize a topic and persist its artifacts through the persistence API."""
    return service.summarize_and_persist(
        topic_id=req.topic_id,
        discussion_text=req.discussion_text,
        custom_title=req.custom_title,
        existing_info=req.existing_info,
    )

