from typing import Annotated, Iterator, Optional
from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import StreamingResponse

from agent.schemas.chat import ChatRequest, ChatResponse, Citation, SourceDependency
from agent.service.access_guard import AccessGuard, CURRENT_ACCESS_GUARD
from agent.agent import Agent
from agent.auth import verify_agent_key
from agent.streaming.sse import build_sse_event
from agent.service.permission_service import PermissionResolutionError

router = APIRouter()


_agent_instance: Optional[Agent] = None


from agent.runtime.lifecycle import get_application_container

def get_agent() -> Agent:
    return get_application_container().get_agent()


@router.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    agent: Agent = Depends(get_agent),
    _: None = Depends(verify_agent_key),
) -> ChatResponse:
    try:
        return agent.chat(request)
    except PermissionResolutionError as exc:
        raise HTTPException(exc.status_code, exc.code, headers={"Cache-Control": "no-store"}) from exc


@router.get("/chat/history")
def chat_history(
    limit: int = 50,
    agent: Agent = Depends(get_agent),
    _: None = Depends(verify_agent_key),
) -> list[dict]:
    # Legacy global audit plaintext has neither actor scope nor dependencies.
    # Durable, authenticated Web history is the sole conversation read path.
    raise HTTPException(410, "legacy_history_quarantined", headers={"Cache-Control": "no-store"})



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
    try:
        events = list(agent.stream_chat(request))
    except PermissionResolutionError as exc:
        raise HTTPException(exc.status_code, exc.code, headers={"Cache-Control": "no-store"}) from exc
    def event_stream():
        for event_name, event_data in events:
            yield build_sse_event(event_name, event_data)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})


from pydantic import BaseModel, Field
from agent.llm.llm_client import LLMClient
from agent.service.topic_summarization_service import TopicSummarizationService
from data_persistence.topics import TopicArtifactRepository


class SummarizeTopicRequest(BaseModel):
    topic_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,200}$')
    discussion_text: str
    custom_title: Optional[str] = None
    existing_info: Optional[dict] = None
    source_dependencies: list[SourceDependency] = Field(default_factory=list, max_length=500)
    provenance_complete: bool = False


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
    agent: Agent = Depends(get_agent),
    user_id: Annotated[str | None, Header(alias="X-User-ID")] = None,
    internal_token: Annotated[str | None, Header(alias="X-Agent-Internal-Token")] = None,
) -> SummarizeTopicResponse:
    """Summarize a topic and persist its artifacts through the persistence API."""
    import secrets
    from agent.config.settings import settings
    if not settings.AGENT_INTERNAL_TOKEN or not secrets.compare_digest(internal_token or "", settings.AGENT_INTERNAL_TOKEN):
        raise HTTPException(403, "forbidden")
    guard = AccessGuard(agent.permission_service, ChatRequest(query="", user_id=user_id, session_id=req.topic_id), "topic-summary")
    guard.allowed_documents([])
    with agent.permission_service._connect() as connection:
        if connection.execute("SELECT 1 FROM topic_members WHERE topic_id=? AND user_id=? AND role IN ('owner','editor')", (req.topic_id, user_id)).fetchone() is None:
            raise HTTPException(404, "topic_not_found")
    if not req.provenance_complete or not guard._inherit_if_allowed(req.source_dependencies):
        raise HTTPException(409, "source_provenance_incomplete")
    token = CURRENT_ACCESS_GUARD.set(guard)
    try:
        result = service.summarize_and_persist(topic_id=req.topic_id, discussion_text=req.discussion_text,
            custom_title=req.custom_title, existing_info=req.existing_info or {})
        guard.check_dependencies()
        return result
    finally:
        CURRENT_ACCESS_GUARD.reset(token)
