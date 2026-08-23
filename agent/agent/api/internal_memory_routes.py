"""Token-protected, BFF-only transport endpoints for persistent Memory."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse

from agent.agent import Agent
from agent.api.chat_routes import get_agent
from agent.config.settings import settings
from agent.memory.compaction_planner import CompactionPlanner
from agent.schemas.chat import (
    CompactionPlanResponse,
    CompactionPlanRequest,
    InternalChatRequest,
    InternalChatResponse,
    MemoryContextInput,
    ResetShortWindowRequest,
    ResetShortWindowResponse,
)


router = APIRouter()


def require_agent_internal_token(
    x_agent_internal_token: Annotated[
        str | None,
        Header(alias="X-Agent-Internal-Token"),
    ] = None,
) -> None:
    """Reject every non-BFF request without disclosing token failure details."""

    expected_token = settings.AGENT_INTERNAL_TOKEN
    provided_token = x_agent_internal_token or ""
    if not expected_token or not secrets.compare_digest(provided_token, expected_token):
        raise HTTPException(status_code=403, detail="forbidden")


def require_json_content_type(
    content_type: Annotated[str | None, Header()] = None,
) -> None:
    media_type = (content_type or "").split(";", maxsplit=1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(status_code=415, detail="unsupported_media_type")


def _reject_invalid_memory_context() -> None:
    # Keep validation failures stable and never echo Memory/Facts/Tail contents.
    raise HTTPException(status_code=422, detail="invalid_memory_context")


def validate_memory_context(context: MemoryContextInput) -> None:
    """Validate cross-field transport invariants that cannot live in the DTO alone."""

    snapshot = context.snapshot
    if snapshot is not None:
        if snapshot.revision != context.revision:
            _reject_invalid_memory_context()
        if snapshot.covered_to_sequence >= context.current_sequence:
            _reject_invalid_memory_context()

    previous_sequence = 0
    message_ids: set[str] = set()
    for message in context.tail:
        if message.revision != context.revision:
            _reject_invalid_memory_context()
        if message.sequence >= context.current_sequence:
            _reject_invalid_memory_context()
        if snapshot is not None and message.sequence <= snapshot.covered_to_sequence:
            _reject_invalid_memory_context()
        if message.sequence <= previous_sequence:
            _reject_invalid_memory_context()
        if message.id == context.current_message_id or message.id in message_ids:
            _reject_invalid_memory_context()
        previous_sequence = message.sequence
        message_ids.add(message.id)


def validate_compaction_request(request: CompactionPlanRequest) -> None:
    """Reject malformed versioned input without reading storage."""

    if (
        request.active_snapshot is not None
        and request.active_snapshot.revision != request.revision
    ):
        _reject_invalid_memory_context()

    previous_sequence = 0
    message_ids: set[str] = set()
    for message in request.messages:
        if message.revision != request.revision:
            _reject_invalid_memory_context()
        if message.sequence <= previous_sequence:
            _reject_invalid_memory_context()
        if message.id in message_ids:
            _reject_invalid_memory_context()
        previous_sequence = message.sequence
        message_ids.add(message.id)


@router.post("/chat", response_model=InternalChatResponse)
def internal_chat(
    request: InternalChatRequest,
    _: Annotated[None, Depends(require_agent_internal_token)],
    __: Annotated[None, Depends(require_json_content_type)],
    agent: Annotated[Agent, Depends(get_agent)],
) -> InternalChatResponse | JSONResponse:
    """Resolve trusted Memory context and keep the result inside the BFF contract."""

    if not settings.PERSISTENT_MEMORY_ENABLED:
        return JSONResponse(
            status_code=409,
            content={"code": "persistent_memory_disabled"},
        )

    validate_memory_context(request.memory_context)
    response, memory_decision = agent.chat_with_memory(request)
    return InternalChatResponse(
        response=response,
        memory_decision=memory_decision,
    )


@router.post("/memory/compaction-plan", response_model=CompactionPlanResponse)
def compaction_plan(
    request: CompactionPlanRequest,
    _: Annotated[None, Depends(require_agent_internal_token)],
    __: Annotated[None, Depends(require_json_content_type)],
) -> CompactionPlanResponse:
    """Return a pure post-persistence plan; the BFF remains the sole writer."""

    validate_compaction_request(request)
    return CompactionPlanner().plan(request)


@router.post("/memory/reset-short-window", response_model=ResetShortWindowResponse)
def reset_short_window(
    request: ResetShortWindowRequest,
    _: Annotated[None, Depends(require_agent_internal_token)],
    __: Annotated[None, Depends(require_json_content_type)],
    agent: Annotated[Agent, Depends(get_agent)],
) -> ResetShortWindowResponse:
    """Clear only legacy in-process ConversationMemory after a Web transaction."""

    agent.memory.clear(request.chat_id)
    return ResetShortWindowResponse(status="ok")
