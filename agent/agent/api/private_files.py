from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse

from data_persistence.file_settings import AttachmentSettings
from pipeline.ingestion.uploads import ingest_persisted_document
from tool_layer.attachment_tools import search_attachment_evidence
from tool_layer.search_library_tool import search_library_evidence
from data_persistence.file_settings import validate_library_configuration
from data_persistence.file_crypto import decrypt_file, encrypt_file
from tool_layer.parse_attachment_tool import parse_attachment_context
from parsers.office_runtime import remove_office_tree
from data_persistence.private_files import get_private_file_store
from pipeline.files.validation import AttachmentValidationError, safe_filename, validate_file
from data_persistence.vector import get_file_vector_store
from pipeline.files.previews import build_encrypted_previews

from data_persistence.file_contracts import (
    EvidenceCorrection, SearchRequest, LibrarySearchRequest, ScopeUpdate, LibraryActivation
)


LOGGER = logging.getLogger("attachment-service")
SETTINGS = AttachmentSettings.from_env()
SETTINGS.data_dir.mkdir(parents=True, exist_ok=True)
STORE = get_private_file_store()
VECTOR_STORE = get_file_vector_store()
STOP = threading.Event()
ATTACHMENT_ID_PATTERN = re.compile(r"^(?:att|ver)_[A-Za-z0-9]{1,60}$")


def _blob_aad(record: dict[str, Any]) -> bytes:
    return f"{record['dedupe_domain']}:{record['sha256']}".encode()


def _authorize(authorization: str = Header(default="")) -> None:
    expected = f"Bearer {SETTINGS.internal_secret}"
    if not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="invalid internal credential")


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    excluded = {"blob_path", "key_id", "dedupe_domain", "deleted_at"}
    return {key: value for key, value in record.items() if key not in excluded}


def _persist_uploaded_file(
    *, temporary: Path, attachment_id: str, filename: str, mime_type: str,
    extension: str, size: int, sha256: str, owner_id: str,
    dedupe_domain: str, scope: str, expires_at: int | None,
    status: str, error_code: str = "", enqueue_parse: bool = False,
) -> dict[str, Any]:
    existing_blob = STORE.get_blob(dedupe_domain, sha256)
    if existing_blob:
        blob = STORE.acquire_blob(
            existing_blob["storage_key"], dedupe_domain, sha256,
            existing_blob["blob_path"], existing_blob["key_id"],
        )
    else:
        domain_hash = hashlib.sha256(dedupe_domain.encode()).hexdigest()[:16]
        storage_key = f"blob_{domain_hash}_{sha256}"
        created_blob_path = SETTINGS.data_dir / "blobs" / domain_hash[:2] / f"{storage_key}.blob"
        encrypt_file(
            temporary, created_blob_path, SETTINGS.encryption_key,
            f"{dedupe_domain}:{sha256}".encode(),
        )
        blob = STORE.acquire_blob(
            storage_key, dedupe_domain, sha256,
            str(created_blob_path), SETTINGS.encryption_key_id,
        )
    try:
        now = int(time.time())
        STORE.create_attachment({
            "id": attachment_id, "filename": filename, "mime_type": mime_type,
            "extension": extension, "size_bytes": size, "sha256": sha256,
            "owner_id": owner_id, "dedupe_domain": dedupe_domain, "scope": scope,
            "status": status, "blob_path": blob["blob_path"], "key_id": blob["key_id"],
            "created_at": now, "updated_at": now, "expires_at": expires_at,
            "error_code": error_code,
        })
    except Exception:
        released = STORE.release_blob(dedupe_domain, sha256)
        if released:
            Path(released).unlink(missing_ok=True)
        raise
    if enqueue_parse:
        STORE.enqueue(f"job_{uuid4().hex}", attachment_id, "parse")
    return STORE.get_attachment(attachment_id, include_deleted=True) or {}


def _migrate_blob_domain(record: dict[str, Any], new_domain: str) -> None:
    if new_domain == record["dedupe_domain"]:
        return
    if not (new_domain.startswith("topic:") or new_domain.startswith("user:")):
        raise ValueError("invalid_dedupe_domain")
    temporary = SETTINGS.data_dir / "temporary" / f"migrate_{uuid4().hex}{record['extension']}"
    new_blob: dict[str, Any] | None = None
    try:
        decrypt_file(Path(record["blob_path"]), temporary, SETTINGS.encryption_key, _blob_aad(record))
        existing = STORE.get_blob(new_domain, record["sha256"])
        if existing:
            new_blob = STORE.acquire_blob(
                existing["storage_key"], new_domain, record["sha256"],
                existing["blob_path"], existing["key_id"],
            )
        else:
            storage_key = f"blob_{uuid4().hex}"
            domain_hash = hashlib.sha256(new_domain.encode()).hexdigest()
            blob_path = SETTINGS.data_dir / "blobs" / domain_hash[:2] / f"{storage_key}.blob"
            encrypt_file(
                temporary, blob_path, SETTINGS.encryption_key,
                f"{new_domain}:{record['sha256']}".encode(),
            )
            new_blob = STORE.acquire_blob(
                storage_key, new_domain, record["sha256"], str(blob_path), SETTINGS.encryption_key_id,
            )
        STORE.update_attachment(
            record["id"], dedupe_domain=new_domain,
            blob_path=new_blob["blob_path"], key_id=new_blob["key_id"],
        )
    except Exception:
        if new_blob:
            unused = STORE.release_blob(new_domain, record["sha256"])
            if unused:
                Path(unused).unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)
    old_unused = STORE.release_blob(record["dedupe_domain"], record["sha256"])
    if old_unused:
        Path(old_unused).unlink(missing_ok=True)


def _worker() -> None:
    while not STOP.wait(0.5):
        job = STORE.claim_job()
        if not job:
            continue
        attachment = STORE.get_attachment(
            job["attachment_id"], include_deleted=job["kind"] == "delete"
        )
        if not attachment:
            STORE.complete_job(job["id"], error_code="attachment_not_found")
            continue
        if job["kind"] == "delete":
            try:
                if VECTOR_STORE is not None:
                    VECTOR_STORE.delete_document_chunks(str(attachment.get("vector_ref") or attachment["id"]))
                derivative_paths = [item["blob_path"] for item in STORE.list_derivatives(attachment["id"])]
                blob = STORE.get_blob(attachment["dedupe_domain"], attachment["sha256"])
                if blob and int(blob["ref_count"]) <= 1:
                    Path(blob["blob_path"]).unlink(missing_ok=True)
                for derivative_path in derivative_paths:
                    Path(derivative_path).unlink(missing_ok=True)
                STORE.release_blob(attachment["dedupe_domain"], attachment["sha256"])
                STORE.purge(attachment["id"])
            except Exception as exc:
                LOGGER.warning(
                    "delete retry attachment_id=%s attempts=%s error=%s",
                    attachment["id"], job["attempts"], exc.__class__.__name__,
                )
                if int(job["attempts"]) < 10:
                    time.sleep(1)
                    STORE.requeue_job(job["id"], "delete_failed")
                else:
                    STORE.complete_job(job["id"], error_code="delete_failed")
            continue
        if job["kind"] == "cleanup_index":
            try:
                if VECTOR_STORE is not None:
                    VECTOR_STORE.delete_document_chunks(str(job["payload"].get("vector_ref") or attachment["id"]))
                STORE.complete_job(job["id"])
                LOGGER.info("LIBRARY_CLEANUP_COMPLETE version_id=%s", attachment["id"])
            except Exception as exc:
                LOGGER.warning(
                    "LIBRARY_CLEANUP_RETRY version_id=%s attempts=%s error=%s",
                    attachment["id"], job["attempts"], exc.__class__.__name__,
                )
                if int(job["attempts"]) < 10:
                    STORE.requeue_job(job["id"], "cleanup_failed")
                else:
                    STORE.complete_job(job["id"], error_code="cleanup_failed")
            continue
        if job["kind"] == "copy_parse":
            source_id = str(job["payload"].get("source_id") or "")
            source = STORE.get_attachment(source_id)
            parsed = STORE.load_parsed_document(source_id)
            if source and source["status"] in {"ready", "needs_review"} and source["owner_id"] == attachment["owner_id"] and source["sha256"] == attachment["sha256"] and parsed:
                STORE.save_parsed_document(attachment["id"], parsed)
                STORE.complete_job(job["id"])
            elif source and source["status"] == "parsing":
                STORE.requeue_job(job["id"], "awaiting_parse")
                time.sleep(0.1)
            else:
                STORE.transition_attachment(attachment["id"], "failed", error_code="source_parse_failed")
                STORE.complete_job(job["id"], error_code="source_parse_failed")
            continue
        temporary = SETTINGS.data_dir / "temporary" / f"{attachment['id']}{attachment['extension']}"
        preserve_active = bool(job["payload"].get("preserve_active")) and bool(attachment.get("active"))
        try:
            if not preserve_active:
                STORE.transition_attachment(attachment["id"], "parsing", error_code="")
            if job["kind"] == "parse":
                decrypt_file(Path(attachment["blob_path"]), temporary, SETTINGS.encryption_key, _blob_aad(attachment))
                result = parse_attachment_context(
                    temporary, attachment["id"], STORE, timeout=SETTINGS.parse_timeout_seconds,
                )
                if attachment.get("scope") != "library":
                    STORE.replace_evidence(attachment["id"], result["items"])
                derivatives = build_encrypted_previews(
                    temporary, attachment["id"], attachment["extension"], SETTINGS.data_dir,
                    SETTINGS.encryption_key, SETTINGS.encryption_key_id,
                )
                old_derivatives = STORE.replace_derivatives(attachment["id"], derivatives)
                current_derivatives = {item["blob_path"] for item in derivatives}
                for old_path in old_derivatives:
                    if old_path not in current_derivatives:
                        Path(old_path).unlink(missing_ok=True)
                if attachment.get("scope") != "library":
                    preview_required = attachment["extension"] in {".doc", ".docx", ".ppt", ".pptx"}
                    needs_review = not result["items"] or (preview_required and not derivatives) or any(
                        item.get("confidence") is not None and item["confidence"] < 0.8
                        for item in result["items"]
                    )
                    STORE.transition_attachment(attachment["id"], "needs_review" if needs_review else "ready")
                STORE.complete_job(job["id"])
                continue
            ingest_persisted_document(STORE, VECTOR_STORE, attachment, job)
            STORE.complete_job(job["id"])
        except Exception as exc:
            code = str(exc) if str(exc) in {
                "ocr_backend_unavailable", "parse_timeout", "empty_parse_result",
                "library_vector_index_disabled", "attachment_vector_index_unavailable", "vector_index_unavailable",
                "empty_structure_result",
            } else "parse_failed"
            LOGGER.warning("parse failed attachment_id=%s hash=%s error=%s", attachment["id"], attachment["sha256"][:12], code)
            current = STORE.get_attachment(attachment["id"], include_deleted=True)
            if not current or current["status"] in {"deleted", "expired"}:
                STORE.complete_job(job["id"], error_code="parse_cancelled")
            elif int(job["attempts"]) < 3:
                time.sleep(1)
                STORE.requeue_job(job["id"], code)
            elif preserve_active:
                STORE.update_attachment(attachment["id"], status="ready", error_code="reindex_failed")
                STORE.complete_job(job["id"], error_code="reindex_failed")
            else:
                STORE.transition_attachment(attachment["id"], "failed", error_code=code)
                STORE.complete_job(job["id"], error_code=code)
        finally:
            temporary.unlink(missing_ok=True)


def _cleanup() -> None:
    while not STOP.wait(60):
        for attachment_id in STORE.expire():
            if not STORE.has_active_job(attachment_id, "delete"):
                STORE.enqueue(f"job_{uuid4().hex}", attachment_id, "delete")
        cutoff = time.time() - 3600
        for temporary in (SETTINGS.data_dir / "temporary").glob("*"):
            try:
                if temporary.stat().st_mtime >= cutoff:
                    continue
                if temporary.is_dir():
                    remove_office_tree(temporary)
                else:
                    temporary.unlink(missing_ok=True)
            except OSError:
                LOGGER.warning("temporary cleanup deferred type=%s", "directory" if temporary.is_dir() else "file")


@asynccontextmanager
async def lifespan(_: FastAPI):
    STOP.clear()
    validate_library_configuration(
        library_enabled=os.getenv("PERSONAL_LIBRARY_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
        vector_enabled=VECTOR_STORE is not None,
    )
    workers = [threading.Thread(target=_worker, daemon=True, name="attachment-parser")]
    workers.append(threading.Thread(target=_cleanup, daemon=True, name="attachment-cleanup"))
    for worker in workers:
        worker.start()
    yield
    STOP.set()
    for worker in workers:
        worker.join(timeout=3)


app = FastAPI(title="Private File Storage", version="1.0.0", lifespan=lifespan)


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", dependencies=[Depends(_authorize)])
def ready() -> dict[str, Any]:
    return {"status": "ready"}


@app.post("/v1/attachments/{attachment_id}", status_code=201, dependencies=[Depends(_authorize)])
async def upload(
    attachment_id: str,
    request: Request,
    x_filename_b64: str = Header(),
    x_owner_id: str = Header(),
    x_dedupe_domain: str = Header(),
    x_scope: str = Header(),
    x_expires_at: int | None = Header(default=None),
    x_knowledge_base_id: str | None = Header(default=None),
    x_document_id: str | None = Header(default=None),
    x_version_id: str | None = Header(default=None),
    x_source_scope: str | None = Header(default=None),
    x_chat_id: str | None = Header(default=None),
    x_topic_id: str | None = Header(default=None),
    x_library_document_id: str | None = Header(default=None),
    x_library_version_id: str | None = Header(default=None),
    x_library_kb_id: str | None = Header(default=None),
) -> dict[str, Any]:
    if not ATTACHMENT_ID_PATTERN.fullmatch(attachment_id):
        raise HTTPException(400, "invalid attachment id")
    if x_scope not in {"draft", "chat", "topic", "library"}:
        raise HTTPException(400, "invalid attachment scope")
    if x_scope == "library" and (
        not x_knowledge_base_id
        or not x_document_id
        or not x_version_id
        or x_source_scope != "personal"
        or x_expires_at is not None
    ):
        raise HTTPException(400, "invalid library identity")
    companion = (x_library_document_id, x_library_version_id, x_library_kb_id)
    if any(companion) and (not all(companion) or x_scope == "library" or not ATTACHMENT_ID_PATTERN.fullmatch(x_library_version_id or "")):
        raise HTTPException(400, "invalid personal library identity")
    try:
        filename = safe_filename(base64.urlsafe_b64decode(x_filename_b64 + "=" * (-len(x_filename_b64) % 4)).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(400, "invalid filename header") from exc
    temporary_dir = SETTINGS.data_dir / "temporary"
    temporary_dir.mkdir(parents=True, exist_ok=True)
    temporary = temporary_dir / f"upload_{uuid4().hex}"
    digest = hashlib.sha256()
    size = 0
    hard_limit = SETTINGS.max_document_bytes
    try:
        with temporary.open("xb") as target:
            async for chunk in request.stream():
                size += len(chunk)
                if size > hard_limit:
                    raise AttachmentValidationError("file_too_large", "file exceeds configured limit")
                digest.update(chunk)
                target.write(chunk)
        declared_length = request.headers.get("content-length")
        if declared_length is None or not declared_length.isdigit() or int(declared_length) != size:
            raise AttachmentValidationError("length_mismatch", "declared length does not match uploaded bytes")
        validated = validate_file(
            temporary, filename, request.headers.get("content-type", "application/octet-stream"), size,
            max_image_bytes=SETTINGS.max_image_bytes,
            max_document_bytes=SETTINGS.max_document_bytes,
            max_pdf_pages=SETTINGS.max_pdf_pages,
            max_image_pixels=SETTINGS.max_image_pixels,
        )
        record = _persist_uploaded_file(
            temporary=temporary, attachment_id=attachment_id, filename=filename,
            mime_type=request.headers.get("content-type", ""), extension=validated.extension,
            size=size, sha256=digest.hexdigest(), owner_id=x_owner_id,
            dedupe_domain=x_dedupe_domain, scope=x_scope, expires_at=x_expires_at,
            status="parsing",
        )
        if x_scope == "library":
            STORE.update_attachment(
                attachment_id,
                knowledge_base_id=x_knowledge_base_id,
                document_id=x_document_id,
                version_id=x_version_id,
                source_scope="personal",
                active=0,
            )
        if all(companion):
            # Persist an independent owner-private raw file. The parsed snapshot
            # is reused by a durable job; no second format parsing is needed.
            _persist_uploaded_file(
                temporary=temporary, attachment_id=x_library_version_id, filename=filename,
                mime_type=request.headers.get("content-type", ""), extension=validated.extension,
                size=size, sha256=digest.hexdigest(), owner_id=x_owner_id,
                dedupe_domain=f"user:{x_owner_id}", scope="library", expires_at=None, status="parsing",
            )
            STORE.update_attachment(
                x_library_version_id, knowledge_base_id=x_library_kb_id,
                document_id=x_library_document_id, version_id=x_library_version_id,
                source_scope="personal", active=0,
            )
        if x_scope == "library":
            LOGGER.info(
                "LIBRARY_UPLOAD owner_hash=%s knowledge_base_id=%s document_id=%s version_id=%s",
                hashlib.sha256(x_owner_id.encode()).hexdigest()[:12], x_knowledge_base_id,
                x_document_id, x_version_id,
            )
        STORE.update_attachment(attachment_id, chat_id=x_chat_id, topic_id=x_topic_id)
        STORE.enqueue(f"job_{uuid4().hex}", attachment_id, "parse")
        if all(companion):
            STORE.enqueue(f"job_{uuid4().hex}", x_library_version_id, "copy_parse", {"source_id": attachment_id})
        return _public_record(STORE.get_attachment(attachment_id) or record)
    except AttachmentValidationError as exc:
        raise HTTPException(422, {"code": exc.code, "message": str(exc)}) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, {"code": "upload_failed"}) from exc
    finally:
        temporary.unlink(missing_ok=True)


@app.get("/v1/attachments/{attachment_id}", dependencies=[Depends(_authorize)])
def metadata(attachment_id: str) -> dict[str, Any]:
    record = STORE.get_attachment(attachment_id)
    if not record:
        raise HTTPException(404, "attachment not found")
    public = _public_record(record)
    public["previews"] = [
        {key: value for key, value in item.items() if key not in {"blob_path", "key_id"}}
        for item in STORE.list_derivatives(attachment_id)
    ]
    return public


@app.get("/v1/attachments/{attachment_id}/evidence", dependencies=[Depends(_authorize)])
def evidence(attachment_id: str) -> dict[str, Any]:
    if not STORE.get_attachment(attachment_id):
        raise HTTPException(404, "attachment not found")
    return {"items": STORE.list_evidence([attachment_id])}


@app.patch("/v1/attachments/{attachment_id}/evidence/{evidence_id}", dependencies=[Depends(_authorize)])
def correct_evidence(attachment_id: str, evidence_id: str, body: EvidenceCorrection) -> dict[str, Any]:
    record = STORE.get_attachment(attachment_id)
    if not record:
        raise HTTPException(404, "attachment not found")
    updated = STORE.revise_evidence(attachment_id, evidence_id, body.expected_version, body.corrected_content, body.reason, body.actor_id, f"aer_{uuid4().hex}")
    if updated is None:
        raise HTTPException(409, "evidence version conflict")
    return {"items": updated}


@app.get("/v1/attachments/{attachment_id}/evidence/{evidence_id}/revisions", dependencies=[Depends(_authorize)])
def revisions(attachment_id: str, evidence_id: str) -> dict[str, Any]:
    if not STORE.get_attachment(attachment_id):
        raise HTTPException(404, "attachment not found")
    return {"items": STORE.list_revisions(attachment_id, evidence_id)}


@app.get("/v1/attachments/{attachment_id}/content", dependencies=[Depends(_authorize)])
def content(attachment_id: str, expected_hash: str | None = None, expected_version: int | None = None) -> FileResponse:
    record = STORE.get_attachment(attachment_id)
    if not record or record["status"] in {"expired", "deleted", "quarantined"}:
        raise HTTPException(404, "attachment not found")
    if (expected_hash is not None and record["sha256"] != expected_hash) or (expected_version is not None and record["evidence_version"] != expected_version):
        raise HTTPException(409, "source_evidence_changed")
    if expected_hash is not None and record["status"] not in {"ready", "needs_review"}:
        raise HTTPException(409, "source_not_ready")
    preview = SETTINGS.data_dir / "temporary" / f"download_{uuid4().hex}{record['extension']}"
    decrypt_file(Path(record["blob_path"]), preview, SETTINGS.encryption_key, _blob_aad(record))
    return FileResponse(preview, media_type=record["mime_type"], filename=record["filename"], background=_unlink_task(preview))


@app.get("/v1/attachments/{attachment_id}/previews/{derivative_id}", dependencies=[Depends(_authorize)])
def preview(attachment_id: str, derivative_id: str) -> FileResponse:
    record = STORE.get_attachment(attachment_id)
    derivative = STORE.get_derivative(attachment_id, derivative_id)
    if not record or not derivative or record["status"] in {"expired", "deleted", "quarantined"}:
        raise HTTPException(404, "preview not found")
    temporary = SETTINGS.data_dir / "temporary" / f"preview_{uuid4().hex}.webp"
    decrypt_file(
        Path(derivative["blob_path"]), temporary, SETTINGS.encryption_key,
        f"{attachment_id}:{derivative_id}".encode(),
    )
    return FileResponse(
        temporary, media_type=derivative["mime_type"],
        background=_unlink_task(temporary),
    )


def _unlink_task(path: Path):
    from starlette.background import BackgroundTask
    return BackgroundTask(path.unlink, missing_ok=True)


@app.post("/v1/attachments/{attachment_id}/retry", dependencies=[Depends(_authorize)])
def retry(attachment_id: str) -> dict[str, Any]:
    record = STORE.get_attachment(attachment_id)
    if not record:
        raise HTTPException(404, "attachment not found")
    if record["status"] not in {"failed", "needs_review", "ready"}:
        raise HTTPException(409, "attachment is not retryable")
    preserve_active = record["status"] == "ready" and bool(record.get("active"))
    if not preserve_active:
        STORE.transition_attachment(attachment_id, "parsing", error_code="")
    STORE.enqueue(
        f"job_{uuid4().hex}", attachment_id, "parse",
        {"preserve_active": preserve_active},
    )
    return _public_record(STORE.get_attachment(attachment_id) or {})


@app.post("/v1/attachments/{attachment_id}/library/activate", dependencies=[Depends(_authorize)])
def activate_library_version(attachment_id: str, body: LibraryActivation) -> dict[str, Any]:
    try:
        result = STORE.activate_library_version(
            attachment_id,
            body.version_number,
            explicit=body.explicit,
        )
    except KeyError as exc:
        raise HTTPException(404, "library version not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    for stale_id in result["stale_ids"]:
        stale = STORE.get_attachment(stale_id)
        if stale and not STORE.has_active_job(stale_id, "cleanup_index"):
            STORE.enqueue(
                f"job_{uuid4().hex}", stale_id, "cleanup_index",
                {"vector_ref": str(stale.get("vector_ref") or stale_id)},
            )
    LOGGER.info(
        "LIBRARY_ACTIVE_SWITCH version_id=%s version_number=%s activated=%s stale_count=%s",
        attachment_id,
        body.version_number,
        result["activated"],
        len(result["stale_ids"]),
    )
    return result


@app.patch("/v1/attachments/{attachment_id}/scope", dependencies=[Depends(_authorize)])
def update_scope(attachment_id: str, body: ScopeUpdate) -> dict[str, Any]:
    if body.scope not in {"chat", "topic"}:
        raise HTTPException(422, "invalid scope")
    record = STORE.get_attachment(attachment_id)
    if not record:
        raise HTTPException(404, "attachment not found")
    if body.scope == "topic":
        if not body.dedupe_domain or not body.dedupe_domain.startswith("topic:"):
            raise HTTPException(422, "topic dedupe domain is required")
        if body.topic_id and body.topic_id != body.dedupe_domain.removeprefix('topic:'):
            raise HTTPException(422, 'topic scope identity mismatch')
        try:
            _migrate_blob_domain(record, body.dedupe_domain)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    topic_id = body.topic_id
    if body.scope == 'topic':
        expected_topic = body.dedupe_domain.removeprefix('topic:')
        topic_id = expected_topic
    STORE.update_attachment(attachment_id, scope=body.scope, expires_at=body.expires_at,
        chat_id=body.chat_id if body.scope == 'chat' else record.get('chat_id'), topic_id=topic_id)
    return _public_record(STORE.get_attachment(attachment_id) or {})


@app.delete("/v1/attachments/{attachment_id}", status_code=204, dependencies=[Depends(_authorize)])
def delete(attachment_id: str) -> None:
    record = STORE.get_attachment(attachment_id)
    if not record:
        return
    STORE.soft_delete(attachment_id)
    if record.get("scope") == "library":
        LOGGER.info(
            "LIBRARY_DELETE document_id=%s version_id=%s",
            record.get("document_id"), record.get("version_id"),
        )
    if not STORE.has_active_job(attachment_id, "delete"):
        STORE.enqueue(f"job_{uuid4().hex}", attachment_id, "delete")


@app.post("/v1/search", dependencies=[Depends(_authorize)])
def search(body: SearchRequest) -> dict[str, Any]:
    return search_attachment_evidence(body, STORE)


@app.post("/v1/library/search", dependencies=[Depends(_authorize)])
def search_library(body: LibrarySearchRequest) -> dict[str, Any]:
    return search_library_evidence(body, STORE, VECTOR_STORE)
