"""BFF-only live access and authoritative catalogue/source projections."""
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from agent.agent import Agent
from agent.api.chat_routes import get_agent
from agent.auth import verify_agent_key
from agent.service.permission_service import PermissionResolutionError
from toolset.tool_layer.evidence_metadata import check_expected_source, source_metadata, DocumentVersionConflict

router = APIRouter(prefix="/access", dependencies=[Depends(verify_agent_key)])


def require_user_id(x_user_id: Annotated[str | None, Header(alias="X-User-ID")] = None) -> str:
    if not x_user_id or not x_user_id.strip():
        raise HTTPException(401, "trusted_identity_required")
    return x_user_id


def resolve_access(agent: Agent, user_id: str, doc_ids: list[str] | None = None) -> list[str]:
    try:
        return agent.permission_service.get_accessible_doc_ids_strict(user_id, doc_ids=doc_ids)
    except PermissionResolutionError as exc:
        raise HTTPException(exc.status_code, exc.code, headers={"Cache-Control": "no-store"}) from exc


class AccessCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doc_ids: list[str] = Field(max_length=200)


@router.post("/check")
def check_access(request: AccessCheckRequest, response: Response,
                 user_id: str = Depends(require_user_id), agent: Agent = Depends(get_agent)):
    response.headers["Cache-Control"] = "no-store"
    ids = list(dict.fromkeys(request.doc_ids))
    allowed = resolve_access(agent, user_id, ids)
    return {"allowed_doc_ids": allowed, "denied_doc_ids": [value for value in ids if value not in allowed]}


@router.get("/documents")
def list_documents(response: Response, user_id: str = Depends(require_user_id), agent: Agent = Depends(get_agent)):
    response.headers["Cache-Control"] = "no-store"
    allowed = resolve_access(agent, user_id)
    documents = []
    for doc_id in allowed:
        document = agent.permission_service.source_provider._load(doc_id)
        if document is not None:
            documents.append({**source_metadata(document), **{
                key: document.get(key) for key in ("doc_id", "title", "space", "doc_type", "last_updated", "source_url")
            }})
    # Recheck after reading, before exposing even titles or catalogue counts.
    final_allowed = set(resolve_access(agent, user_id, [item["doc_id"] for item in documents]))
    return {"documents": [item for item in documents if item["doc_id"] in final_allowed]}


@router.get("/documents/{doc_id}/source")
def document_source(doc_id: str, response: Response, expected_version: str | None = None,
                    expected_hash: str | None = None, user_id: str = Depends(require_user_id),
                    agent: Agent = Depends(get_agent)):
    response.headers["Cache-Control"] = "no-store"
    if doc_id not in resolve_access(agent, user_id, [doc_id]):
        raise HTTPException(404, "source_not_found", headers={"Cache-Control": "no-store"})
    try:
        document = agent.permission_service.source_provider._load(doc_id)
        if document is None:
            raise HTTPException(404, "source_not_found", headers={"Cache-Control": "no-store"})
        check_expected_source(document, expected_version=expected_version, expected_hash=expected_hash)
    except DocumentVersionConflict as exc:
        raise HTTPException(409, exc.code, headers={"Cache-Control": "no-store"}) from exc
    except (ValueError, OSError):
        raise HTTPException(404, "source_not_found", headers={"Cache-Control": "no-store"})
    if doc_id not in resolve_access(agent, user_id, [doc_id]):
        raise HTTPException(404, "source_not_found", headers={"Cache-Control": "no-store"})
    return {**document, **source_metadata(document)}
