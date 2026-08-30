"""HTTP control-plane API for manually started Local Deep Research Jobs."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from deep_research.manifest import ManifestResolutionError
from deep_research.repository import (
    ResearchConflictError,
    ResearchNotFoundError,
)
from deep_research.service import ResearchControlPlane, ResearchControlPlaneError
from agent.schemas.research import ResearchJob, ResearchPlan, ResearchReport, ResearchRequest


router = APIRouter(prefix="/research", tags=["research"])


class ResearchApprovalRequest(BaseModel):
    """Client approval snapshot; actor identity comes from the request header."""

    model_config = ConfigDict(extra="forbid")

    plan_version: int = Field(ge=1)
    manifest_hash: str = Field(min_length=8, max_length=128)


_default_control_plane: ResearchControlPlane | None = None


def get_research_control_plane(request: Request) -> ResearchControlPlane:
    """Return the application-scoped durable control plane when available."""

    global _default_control_plane
    runtime = getattr(request.app.state, "research_runtime_service", None)
    if runtime is not None:
        return runtime.control_plane
    if _default_control_plane is None:
        _default_control_plane = ResearchControlPlane()
    return _default_control_plane


def _raise_http_error(exc: Exception) -> None:
    if isinstance(exc, ResearchNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, (ResearchConflictError, ResearchControlPlaneError)):
        code = getattr(exc, "code", "research_conflict")
        raise HTTPException(
            status_code=409,
            detail={"code": code, "message": str(exc)},
        ) from exc
    if isinstance(exc, ManifestResolutionError):
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    raise exc


@router.post(
    "/jobs",
    response_model=ResearchJob,
    status_code=status.HTTP_201_CREATED,
)
def create_research_job(
    request: ResearchRequest,
    user_id: Annotated[str, Header(alias="X-User-ID")] = "local-user",
    control_plane: ResearchControlPlane = Depends(get_research_control_plane),
) -> ResearchJob:
    """Persist a Job and return before durable planning starts."""

    try:
        return control_plane.enqueue_job(request, user_id=user_id)
    except Exception as exc:
        _raise_http_error(exc)
        raise AssertionError("unreachable")


@router.get("/jobs/{research_id}", response_model=ResearchJob)
def get_research_job(
    research_id: str,
    control_plane: ResearchControlPlane = Depends(get_research_control_plane),
) -> ResearchJob:
    try:
        return control_plane.get_job(research_id)
    except Exception as exc:
        _raise_http_error(exc)
        raise AssertionError("unreachable")


@router.get("/jobs/{research_id}/plan", response_model=ResearchPlan)
def get_research_plan(
    research_id: str,
    control_plane: ResearchControlPlane = Depends(get_research_control_plane),
) -> ResearchPlan:
    try:
        return control_plane.get_plan(research_id)
    except Exception as exc:
        _raise_http_error(exc)
        raise AssertionError("unreachable")


@router.post("/jobs/{research_id}/approve", response_model=ResearchJob)
def approve_research_job(
    research_id: str,
    request: ResearchApprovalRequest,
    user_id: Annotated[str, Header(alias="X-User-ID")] = "local-user",
    control_plane: ResearchControlPlane = Depends(get_research_control_plane),
) -> ResearchJob:
    try:
        return control_plane.approve_job(
            research_id,
            plan_version=request.plan_version,
            manifest_hash=request.manifest_hash,
            approved_by=user_id,
        )
    except Exception as exc:
        _raise_http_error(exc)
        raise AssertionError("unreachable")


@router.post("/jobs/{research_id}/cancel", response_model=ResearchJob)
def cancel_research_job(
    research_id: str,
    control_plane: ResearchControlPlane = Depends(get_research_control_plane),
) -> ResearchJob:
    try:
        return control_plane.cancel_job(research_id)
    except Exception as exc:
        _raise_http_error(exc)
        raise AssertionError("unreachable")


@router.get("/jobs/{research_id}/report", response_model=ResearchReport)
def get_research_report(
    research_id: str,
    control_plane: ResearchControlPlane = Depends(get_research_control_plane),
) -> ResearchReport:
    try:
        return control_plane.repository.get_report(research_id)
    except Exception as exc:
        _raise_http_error(exc)
        raise AssertionError("unreachable")


__all__ = ["get_research_control_plane", "router"]
