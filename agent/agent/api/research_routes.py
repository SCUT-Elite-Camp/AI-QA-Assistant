"""HTTP control-plane API for manually started Local Deep Research Jobs."""

from __future__ import annotations

from typing import Annotated
import re
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from deep_research.manifest import ManifestResolutionError
from deep_research.model_report import EvidenceReportSynthesizer
from deep_research.repository import (
    ResearchConflictError,
    ResearchNotFoundError,
)
from deep_research.progress import ResearchProgressService
from deep_research.service import ResearchControlPlane, ResearchControlPlaneError
from agent.schemas.research import (
    ResearchEventsResponse,
    ResearchEventType,
    ResearchJob,
    ResearchPlan,
    ResearchPlanRevisionRequest,
    ResearchProgress,
    ResearchReport,
    ResearchRequest,
    ResearchResultStatus,
)
from agent.config.settings import settings


router = APIRouter(prefix="/research", tags=["research"])


class ResearchApprovalRequest(BaseModel):
    """Client approval snapshot; actor identity comes from the request header."""

    model_config = ConfigDict(extra="forbid")

    plan_version: int = Field(ge=1)
    manifest_hash: str = Field(min_length=8, max_length=128)


class ResearchInteractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)


class ResearchInteractionResponse(BaseModel):
    action: str
    message: str
    job: ResearchJob
    plan: ResearchPlan | None = None


class ResearchEvaluationTrace(BaseModel):
    """Persisted internal artifacts required by the six-layer evaluation."""

    observations: list[dict]
    verified_evidence: list[dict]
    findings: list[dict]
    claims: list[dict]
    verifications: list[dict]


def _resolve_report_conflict(
    report: ResearchReport,
    *,
    conflict_id: str,
    source_number: int,
    reason: str,
) -> ResearchReport:
    conflict = next(item for item in report.conflicts if item.conflict_id == conflict_id)
    chosen = next(
        item for item in conflict.alternatives if item.citation_number == source_number
    )

    resolution = f"用户确认采用来源 {source_number}：{reason}"
    conflicts = [
        item.model_copy(
            update={"resolution_status": "resolved_by_user", "resolution": resolution}
        )
        if item.conflict_id == conflict_id
        else item
        for item in report.conflicts
    ]
    resolved_section = (
        "## 用户确认的冲突处理\n\n"
        f"- **{conflict.subject}**：采用来源 [{source_number}]《{chosen.source_title}》。\n"
        f"  原文：{chosen.value_summary}\n"
        f"  处理理由：{reason}\n\n"
    )
    markdown = report.markdown
    heading = re.match(r"^(#\s+[^\n]+\n+)", markdown)
    if heading:
        markdown = heading.group(1) + resolved_section + markdown[heading.end():]
    else:
        markdown = resolved_section + markdown
    unresolved = any(item.resolution_status == "unresolved" for item in conflicts)
    return report.model_copy(
        update={
            "report_id": f"report-revision-{uuid4().hex}",
            "markdown": markdown,
            "conflicts": conflicts,
            "result_status": (
                ResearchResultStatus.DEGRADED
                if unresolved or report.limitations
                else report.result_status
            ),
            "generated_at": datetime.now(timezone.utc),
        }
    )


def _answer_report_followup(report: ResearchReport, message: str, language: str = "en-US", *, objective: str = "") -> str:
    english = language == "en-US"
    if not report.citations or not settings.LLM_API_KEY:
        return ("The report does not contain enough verified evidence to answer this follow-up." if english else "当前报告没有足够的已核验证据来回答这个追问。")
    evidence = "\n\n".join(
        f"[{item.number}] {item.title}\nSource excerpt: {item.excerpt}"
        for item in report.citations
    )
    prompt = (
        f"Answer the user's follow-up in {'English' if english else 'Chinese'} using the existing report and its frozen verified evidence below. "
        "Do not browse or add facts from memory. Give a direct but complete answer. "
        "Use the report to resolve references such as 'these changes' or 'this report'. "
        "You may calculate differences from cited source values; state the direction of subtraction. "
        "For counts and acceptance arithmetic, use plain text such as 5 + 1 = 6, >= and <=; omit LaTeX dollar delimiters. "
        "The report is context, not independent evidence: verify its claims against the source excerpts. "
        "Every factual paragraph must contain its matching [n] citation. "
        "If the evidence cannot answer it, clearly say what is missing.\n\n"
        f"Original research question: {objective}\n\nFollow-up: {message}\n\nExisting report:\n{report.markdown}\n\nEvidence:\n{evidence}"
    )
    client = EvidenceReportSynthesizer(
        api_base=settings.LLM_API_BASE,
        api_key=settings.LLM_API_KEY,
        model=settings.LLM_MODEL,
    )
    try:
        data = client._chat({
            "model": settings.LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 1200,
        })
        answer = str(data["choices"][0]["message"]["content"]).strip()
        citation_numbers = [int(value) for value in re.findall(r"\[(\d+)]", answer)]
        if answer and citation_numbers and set(citation_numbers).issubset({item.number for item in report.citations}):
            return answer
    except Exception:
        return ("The model service is unavailable. Check API access and model quota, then retry this follow-up."
                if english else "模型服务暂时不可用，请检查接口权限与模型额度后重试。")
    return ("The frozen evidence does not reliably answer this follow-up. Add local sources and start a new research task."
            if english else "这份冻结证据目前无法可靠回答该追问。你可以补充本地资料后重新发起研究。")


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


def get_research_progress_service(
    control_plane: ResearchControlPlane = Depends(get_research_control_plane),
) -> ResearchProgressService:
    """Build a lightweight read service over the application repository."""

    return ResearchProgressService(control_plane.repository)


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


@router.post("/jobs/{research_id}/plan/revisions", response_model=ResearchPlan)
def revise_research_plan(
    research_id: str,
    revision: ResearchPlanRevisionRequest,
    user_id: Annotated[str, Header(alias="X-User-ID")] = "local-user",
    control_plane: ResearchControlPlane = Depends(get_research_control_plane),
) -> ResearchPlan:
    """Persist a new Plan version and invalidate execution until re-approved."""

    try:
        return control_plane.revise_plan(
            research_id,
            revision,
            revised_by=user_id,
        )
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


@router.get("/jobs/{research_id}/progress", response_model=ResearchProgress)
def get_research_progress(
    research_id: str,
    progress_service: ResearchProgressService = Depends(
        get_research_progress_service
    ),
) -> ResearchProgress:
    """Return the authoritative persisted progress read model."""

    try:
        return progress_service.get_progress(research_id)
    except Exception as exc:
        _raise_http_error(exc)
        raise AssertionError("unreachable")


@router.get("/jobs/{research_id}/events", response_model=ResearchEventsResponse)
def get_research_events(
    research_id: str,
    after_event_id: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    progress_service: ResearchProgressService = Depends(
        get_research_progress_service
    ),
) -> ResearchEventsResponse:
    """Return append-only events after a stable cursor for low-cost polling."""

    try:
        return progress_service.get_events(
            research_id,
            after_event_id=after_event_id,
            limit=limit,
        )
    except Exception as exc:
        _raise_http_error(exc)
        raise AssertionError("unreachable")


@router.get(
    "/jobs/{research_id}/evaluation-trace",
    response_model=ResearchEvaluationTrace,
)
def get_research_evaluation_trace(
    research_id: str,
    control_plane: ResearchControlPlane = Depends(get_research_control_plane),
) -> ResearchEvaluationTrace:
    """Expose persisted research artifacts; this never reruns retrieval."""

    try:
        repository = control_plane.repository
        repository.get_job(research_id)
        return ResearchEvaluationTrace(
            observations=[item.model_dump(mode="json") for item in repository.list_observations(research_id)],
            verified_evidence=[item.model_dump(mode="json") for item in repository.list_evidence(research_id)],
            findings=[item.model_dump(mode="json") for item in repository.list_findings(research_id)],
            claims=[item.model_dump(mode="json") for item in repository.list_claims(research_id)],
            verifications=[item.model_dump(mode="json") for item in repository.list_verifications(research_id)],
        )
    except Exception as exc:
        _raise_http_error(exc)
        raise AssertionError("unreachable")


@router.get(
    "/jobs/{research_id}/documents/{doc_id}/source",
    response_class=PlainTextResponse,
)
def get_research_document_source(
    research_id: str,
    doc_id: str,
    control_plane: ResearchControlPlane = Depends(get_research_control_plane),
) -> PlainTextResponse:
    """Open complete source text only for documents frozen into this Job."""

    try:
        manifest = control_plane.get_manifest(research_id)
        if doc_id not in {item.doc_id for item in manifest.documents}:
            raise ResearchNotFoundError(
                f"document '{doc_id}' is not part of research job '{research_id}'"
            )
        _, content = control_plane.source_resolver.read_document(doc_id)
        return PlainTextResponse(
            content,
            headers={"Content-Disposition": "inline"},
        )
    except Exception as exc:
        _raise_http_error(exc)
        raise AssertionError("unreachable")


@router.post(
    "/jobs/{research_id}/messages",
    response_model=ResearchInteractionResponse,
)
def send_research_message(
    research_id: str,
    request: ResearchInteractionRequest,
    user_id: Annotated[str, Header(alias="X-User-ID")] = "local-user",
    control_plane: ResearchControlPlane = Depends(get_research_control_plane),
) -> ResearchInteractionResponse:
    """Apply a persisted conversational command to the Research control plane."""

    message = " ".join(request.message.strip().split())
    interaction_id = uuid4().hex
    repository = control_plane.repository
    try:
        job = control_plane.get_job(research_id)
        repository.append_event(
            research_id=research_id,
            event_key=f"conversation:{interaction_id}:user",
            event_type=ResearchEventType.USER_MESSAGE,
            stage=job.current_stage,
            message=message[:500],
            payload={"content": message},
        )
        english = job.request.report_spec.language == "en-US"
        response_text = "This command is unavailable at the current research stage." if english else "我还不能在当前阶段执行这条指令。"
        action = "clarify"
        plan: ResearchPlan | None = None

        if job.status.value == "awaiting_approval":
            plan = control_plane.get_plan(research_id)
            if re.search(r"(^|[，。\s])(批准|同意|确认|开始执行|按此执行)([，。\s]|$)", message) or re.fullmatch(r"(?:please\s+)?(?:approve|confirm|start)(?:\s+(?:the\s+)?(?:plan|research))?[.!]?", message, re.I):
                job = control_plane.approve_job(
                    research_id,
                    plan_version=plan.version,
                    manifest_hash=plan.manifest_hash or "",
                    approved_by=user_id,
                )
                action = "approved"
                response_text = f"Plan v{plan.version} approved. Research is starting." if english else f"已批准计划 v{plan.version}，现在开始执行研究。"
            elif re.search(r"(^|[，。\s])(取消|停止)([，。\s]|$)", message) or re.fullmatch(r"(?:please\s+)?(?:cancel|stop)(?:\s+(?:the\s+)?(?:task|research))?[.!]?", message, re.I):
                job = control_plane.cancel_job(research_id)
                action = "cancelled"
                response_text = "Research cancelled. Existing state has been preserved." if english else "研究任务已取消，已有状态仍会保留。"
            else:
                match = re.search(r"把?第\s*([一二三四五六七八九十\d]+)\s*(?:步|个任务|项任务)?\s*(?:改为|修改为|调整为)\s*(.+)", message)
                if match:
                    number_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
                    index = int(match.group(1)) if match.group(1).isdigit() else number_map.get(match.group(1), 0)
                    if not 1 <= index <= len(plan.tasks):
                        response_text = f"计划只有 {len(plan.tasks)} 个任务，请说明要修改哪一步。"
                    else:
                        tasks = [task.model_copy(deep=True) for task in plan.tasks]
                        tasks[index - 1] = tasks[index - 1].model_copy(
                            update={"question": match.group(2).strip()}
                        )
                        revised = control_plane.revise_plan(
                            research_id,
                            ResearchPlanRevisionRequest(
                                base_version=plan.version,
                                objective=plan.objective,
                                tasks=tasks,
                                report_spec=plan.report_spec,
                                revision_note=message,
                            ),
                            revised_by=user_id,
                        )
                        plan = revised
                        job = control_plane.get_job(research_id)
                        action = "plan_revised"
                        response_text = f"已将第 {index} 步修改为“{match.group(2).strip()}”，生成计划 v{revised.version}，请重新确认。"
                else:
                    response_text = "Reply \"approve\" to start, or use Edit plan to revise individual tasks." if english else "你可以回复“批准”，或说“把第 2 步改为……”。"
        elif job.status.value == "completed":
            report = repository.get_report(research_id)
            source_match = re.search(r"(?:采用|选择|以)\s*来源\s*(\d+)", message)
            if source_match and report.conflicts:
                source_number = int(source_match.group(1))
                conflict = next(
                    (
                        item for item in report.conflicts
                        if any(alt.citation_number == source_number for alt in item.alternatives)
                    ),
                    None,
                )
                if conflict is not None:
                    report = _resolve_report_conflict(
                        report,
                        conflict_id=conflict.conflict_id,
                        source_number=source_number,
                        reason=message,
                    )
                    repository.save_report(report)
                    repository.append_event(
                        research_id=research_id,
                        event_key=f"conversation:{interaction_id}:conflict",
                        event_type=ResearchEventType.CONFLICT_RESOLVED,
                        stage="completed",
                        message=f"采用来源 {source_number}",
                        payload={
                            "conflict_id": conflict.conflict_id,
                            "citation_number": source_number,
                            "reason": message,
                        },
                    )
                    action = "conflict_resolved"
                    response_text = (
                        f"已采用来源 {source_number} 处理该项冲突，"
                        "并保存了处理意见与对应来源引用。"
                    )
                else:
                    response_text = f"来源 {source_number} 不属于当前待处理冲突，请打开引用后重新选择。"
            else:
                action = "followup_answered"
                response_text = _answer_report_followup(report, message, job.request.report_spec.language, objective=job.request.query)
        elif job.status.value in {"ready", "researching", "synthesizing"}:
            response_text = "研究正在执行中。我会持续更新任务进度；你也可以随时点击取消。"

        repository.append_event(
            research_id=research_id,
            event_key=f"conversation:{interaction_id}:assistant",
            event_type=ResearchEventType.ASSISTANT_MESSAGE,
            stage=job.current_stage,
            message=response_text[:500],
            payload={"action": action, "content": response_text},
        )
        return ResearchInteractionResponse(
            action=action,
            message=response_text,
            job=job,
            plan=plan,
        )
    except Exception as exc:
        _raise_http_error(exc)
        raise AssertionError("unreachable")


__all__ = [
    "get_research_control_plane",
    "get_research_progress_service",
    "router",
]
