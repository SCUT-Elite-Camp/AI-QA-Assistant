"""Token-protected Web-to-Agent Memory transport endpoints (Unit 04a)."""

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from agent.agent import Agent
from agent.api.chat_routes import get_agent
from agent.config.settings import settings
from agent.schemas.chat import (
    CompactionPlanResponse,
    CompactionPlanRequest,
    InternalChatRequest,
    InternalChatResponse,
    ChatResponse,
    ResetShortWindowRequest,
)
from agent.memory.compaction_planner import CompactionPlanner
from agent.streaming.sse import build_sse_event

router = APIRouter()


def require_agent_internal_token(
    x_agent_internal_token: Annotated[str | None, Header()] = None,
) -> None:
    """Reject external callers before they can provide trusted Memory fields."""
    expected = settings.AGENT_INTERNAL_TOKEN
    supplied = x_agent_internal_token or ""
    if not expected or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="Forbidden")


@router.post("/chat", response_model=InternalChatResponse)
def internal_chat(
    request: InternalChatRequest,
    _: Annotated[None, Depends(require_agent_internal_token)],
    agent: Agent = Depends(get_agent),
) -> InternalChatResponse | JSONResponse:
    if not settings.PERSISTENT_MEMORY_ENABLED:
        return JSONResponse(
            status_code=409,
            content={"code": "persistent_memory_disabled"},
        )

    # Context resolution and Fact proposal generation begin in Units 05/06/09.
    # This endpoint only transports already trusted data and preserves ChatResponse.
    return InternalChatResponse(response=agent.chat(request))


@router.post("/chat/retrieval/stream")
def internal_retrieval_stream(
    request: InternalChatRequest,
    _: Annotated[None, Depends(require_agent_internal_token)],
    agent: Agent = Depends(get_agent),
) -> StreamingResponse:
    """Token-protected streaming adapter for server-authorized private sources."""

    def event_stream():
        response: ChatResponse = agent.chat(request)
        yield build_sse_event(
            "citations",
            [citation.model_dump() for citation in response.citations],
        )
        if response.answer:
            for offset in range(0, len(response.answer), 32):
                yield build_sse_event(
                    "token",
                    {"content": response.answer[offset:offset + 32]},
                )
        if response.status == "success":
            yield build_sse_event(
                "done",
                {
                    "trace_id": response.trace_id,
                    "status": response.status,
                    "citations_count": len(response.citations),
                    "chat_title": response.chat_title,
                },
            )
        else:
            yield build_sse_event(
                "error",
                {"message": response.message or "Agent retrieval failed"},
            )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post(
    "/memory/compaction-plan",
    response_model=CompactionPlanResponse,
)
def compaction_plan(
    request: CompactionPlanRequest,
    _: Annotated[None, Depends(require_agent_internal_token)],
) -> CompactionPlanResponse | JSONResponse:
    if not settings.PERSISTENT_MEMORY_ENABLED:
        return JSONResponse(
            status_code=409,
            content={"code": "persistent_memory_disabled"},
        )
    plan = CompactionPlanner().plan(request)
    # The frozen HTTP contract has two exact shapes: the no-op omits optional
    # fields, while an initial compaction explicitly carries a null expectation.
    return JSONResponse(content=plan.model_dump(exclude_none=not plan.should_compact))


@router.post("/memory/reset-short-window")
def reset_short_window(
    request: ResetShortWindowRequest,
    _: Annotated[None, Depends(require_agent_internal_token)],
    agent: Agent = Depends(get_agent),
) -> dict[str, str]:
    agent.memory.clear(request.chat_id)
    return {"status": "ok"}
