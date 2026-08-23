from __future__ import annotations

import asyncio
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
from pydantic import BaseModel, Field

from .config import AttachmentSettings
from .chunking import chunk_attachment_evidence
from .library_service import (
    fuse_library_candidates,
    rebuild_library_projection,
    validate_library_configuration,
)
from .crypto import decrypt_file, encrypt_file
from .parser_runner import parse_with_timeout
from .office import remove_office_tree
from .scanner import MalwareDetected, ScannerUnavailable, scan_file
from .store import AttachmentStore
from .validation import AttachmentValidationError, safe_filename, validate_file
from .vision import LocalVisionBackend
from .vector_index import AttachmentVectorIndex
from .previews import build_encrypted_previews

LOGGER = logging.getLogger("attachment-service")
SETTINGS = AttachmentSettings.from_env()
SETTINGS.data_dir.mkdir(parents=True, exist_ok=True)
STORE = AttachmentStore(SETTINGS.data_dir / "attachments.sqlite3")
VISION = LocalVisionBackend(SETTINGS)
VECTOR_INDEX = AttachmentVectorIndex()
STOP = threading.Event()
VECTOR_PENDING: set[str] = set()
VECTOR_PENDING_LOCK = threading.Lock()
VECTOR_WAKE = threading.Event()
VECTOR_FAILURE_LOGGED: set[str] = set()
SCANNER_READY = False
ATTACHMENT_ID_PATTERN = re.compile(r"^(?:att|ver)_[A-Za-z0-9]{1,60}$")


def _queue_vector_index(attachment_id: str) -> None:
    if not VECTOR_INDEX.enabled:
        return
    with VECTOR_PENDING_LOCK:
        if attachment_id in VECTOR_PENDING:
            return
        VECTOR_PENDING.add(attachment_id)
    VECTOR_WAKE.set()


def _vector_worker() -> None:
    if os.getenv("ATTACHMENT_VECTOR_REBUILD_ON_STARTUP", "false").lower() in {
        "1", "true", "yes",
    }:
        for attachment_id in STORE.list_indexable_attachment_ids():
            _queue_vector_index(attachment_id)
    while not STOP.is_set():
        VECTOR_WAKE.wait(30)
        VECTOR_WAKE.clear()
        with VECTOR_PENDING_LOCK:
            pending = list(VECTOR_PENDING)
        for attachment_id in pending:
            record = STORE.get_attachment(attachment_id)
            if not record or record["status"] not in {"ready", "needs_review"}:
                with VECTOR_PENDING_LOCK:
                    VECTOR_PENDING.discard(attachment_id)
                    VECTOR_FAILURE_LOGGED.discard(attachment_id)
                continue
            try:
                VECTOR_INDEX.replace(attachment_id, STORE.list_evidence([attachment_id]))
            except Exception as exc:
                with VECTOR_PENDING_LOCK:
                    first_failure = attachment_id not in VECTOR_FAILURE_LOGGED
                    VECTOR_FAILURE_LOGGED.add(attachment_id)
                if first_failure:
                    LOGGER.warning(
                        "attachment vector index retry deferred attachment_id=%s error=%s",
                        attachment_id,
                        exc.__class__.__name__,
                    )
            else:
                with VECTOR_PENDING_LOCK:
                    VECTOR_PENDING.discard(attachment_id)
                    VECTOR_FAILURE_LOGGED.discard(attachment_id)


def _blob_aad(record: dict[str, Any]) -> bytes:
    return f"{record['dedupe_domain']}:{record['sha256']}".encode()


class EvidenceCorrection(BaseModel):
    expected_version: int = Field(ge=1)
    corrected_content: str = Field(min_length=1, max_length=200_000)
    reason: str = Field(default="", max_length=500)
    actor_id: str = Field(min_length=1, max_length=128)


class SearchRequest(BaseModel):
    attachment_ids: list[str] = Field(max_length=100)
    query: str = Field(default="", max_length=4000)
    top_k: int = Field(default=10, ge=1, le=50)
    query_vector: list[float] | None = Field(default=None, min_length=1024, max_length=1024)


class LibrarySearchRequest(BaseModel):
    owner_id: str = Field(min_length=1, max_length=128)
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    query: str = Field(default="", max_length=4000)
    top_k: int = Field(default=5, ge=1, le=20)
    doc_ids: list[str] | None = Field(default=None, max_length=100)
    mode: str = Field(default="hybrid", pattern="^(hybrid|vector|bm25)$")
    query_vector: list[float] | None = Field(default=None, min_length=1024, max_length=1024)


class InspectRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    page: int | None = Field(default=None, ge=1, le=200)
    bbox: list[float] | None = None


class ScopeUpdate(BaseModel):
    scope: str
    expires_at: int | None = None
    dedupe_domain: str | None = Field(default=None, min_length=1, max_length=256)


class LibraryActivation(BaseModel):
    version_number: int = Field(ge=1)
    explicit: bool = False


def _authorize(authorization: str = Header(default="")) -> None:
    expected = f"Bearer {SETTINGS.internal_secret}"
    if not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="invalid internal credential")


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    excluded = {"blob_path", "key_id", "dedupe_domain", "deleted_at"}
    return {key: value for key, value in record.items() if key not in excluded}


def _prepare_vision_image(source: Path, extension: str, page: int | None, bbox: list[float] | None, output: Path) -> dict[str, Any]:
    locator: dict[str, Any] = {"page": page, "bbox": bbox}
    if bbox is not None:
        if len(bbox) != 4 or any(value < 0 or value > 1 for value in bbox) or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
            raise ValueError("invalid_bbox")
    if extension == ".pdf":
        import fitz
        document = fitz.open(source)
        try:
            page_number = page or 1
            if page_number > len(document):
                raise ValueError("page_out_of_range")
            pixmap = document[page_number - 1].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            pixmap.save(output)
            locator["page"] = page_number
        finally:
            document.close()
    else:
        if page not in {None, 1}:
            raise ValueError("page_out_of_range")
        from PIL import Image
        with Image.open(source) as image:
            image.convert("RGB").save(output, format="PNG")
        locator["page"] = None
    if bbox is not None:
        from PIL import Image
        with Image.open(output) as image:
            width, height = image.size
            crop = (
                round(bbox[0] * width), round(bbox[1] * height),
                round(bbox[2] * width), round(bbox[3] * height),
            )
            image.crop(crop).save(output, format="PNG")
    return locator


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
            VISION.unload_if_idle()
            continue
        attachment = STORE.get_attachment(
            job["attachment_id"], include_deleted=job["kind"] == "delete"
        )
        if not attachment:
            STORE.complete_job(job["id"], error_code="attachment_not_found")
            continue
        if job["kind"] == "delete":
            try:
                if VECTOR_INDEX.enabled:
                    VECTOR_INDEX.delete(str(attachment.get("vector_ref") or attachment["id"]))
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
                if VECTOR_INDEX.enabled:
                    VECTOR_INDEX.delete(str(job["payload"].get("vector_ref") or attachment["id"]))
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
        temporary = SETTINGS.data_dir / "temporary" / f"{attachment['id']}{attachment['extension']}"
        preserve_active = bool(job["payload"].get("preserve_active")) and bool(attachment.get("active"))
        try:
            if not preserve_active:
                STORE.transition_attachment(attachment["id"], "parsing", error_code="")
            decrypt_file(Path(attachment["blob_path"]), temporary, SETTINGS.encryption_key, _blob_aad(attachment))
            evidence = parse_with_timeout(
                temporary, attachment["id"], attachment["extension"], SETTINGS.parse_timeout_seconds,
            )
            current = STORE.get_attachment(attachment["id"], include_deleted=True)
            if not current or current["status"] in {"deleted", "expired"}:
                STORE.complete_job(job["id"], error_code="parse_cancelled")
                continue
            derivatives = build_encrypted_previews(
                temporary, attachment["id"], attachment["extension"], SETTINGS.data_dir,
                SETTINGS.encryption_key, SETTINGS.encryption_key_id,
            )
            old_derivatives = STORE.replace_derivatives(attachment["id"], derivatives)
            current_derivatives = {item["blob_path"] for item in derivatives}
            for old_path in old_derivatives:
                if old_path not in current_derivatives:
                    Path(old_path).unlink(missing_ok=True)
            if attachment.get("scope") == "library":
                # READY for a library version means both lexical and vector
                # indexes are searchable. Index the new version before the
                # active-version switch so a failure preserves the old one.
                if not evidence:
                    raise RuntimeError("empty_parse_result")
                if not preserve_active:
                    STORE.transition_attachment(attachment["id"], "chunking")
                evidence = chunk_attachment_evidence(
                    evidence,
                    str(attachment.get("version_id") or attachment["id"]),
                    attachment["extension"],
                )
                if not evidence:
                    raise RuntimeError("empty_parse_result")
                LOGGER.info(
                    "LIBRARY_CHUNK_COMPLETE document_id=%s version_id=%s chunks=%s",
                    attachment.get("document_id"), attachment.get("version_id"), len(evidence),
                )
                if not preserve_active:
                    STORE.transition_attachment(attachment["id"], "embedding")
                if not VECTOR_INDEX.enabled:
                    raise RuntimeError("library_vector_index_disabled")
                # Build under a generation-specific ref. The previous active
                # vector/evidence projection remains searchable on failure.
                previous_vector_ref, new_vector_ref = rebuild_library_projection(
                    STORE, VECTOR_INDEX, attachment, evidence, job["id"],
                )
                if not preserve_active:
                    STORE.transition_attachment(attachment["id"], "indexing")
                # READY is an indexed candidate. Web owns the logical active
                # pointer and activates the matching desired version via CAS.
                if preserve_active:
                    STORE.update_attachment(attachment["id"], status="ready", error_code="")
                else:
                    STORE.transition_attachment(attachment["id"], "ready")
                LOGGER.info(
                    "LIBRARY_VERSION_READY document_id=%s version_id=%s version_number=%s",
                    attachment.get("document_id"), attachment.get("version_id"),
                    attachment.get("version_number", 0),
                )
                if previous_vector_ref and previous_vector_ref != new_vector_ref:
                    STORE.enqueue(
                        f"job_{uuid4().hex}", attachment["id"], "cleanup_index",
                        {"vector_ref": previous_vector_ref},
                    )
            else:
                STORE.replace_evidence(attachment["id"], evidence)
                _queue_vector_index(attachment["id"])
            preview_required = attachment["extension"] in {".doc", ".docx", ".ppt", ".pptx"}
            needs_review = not evidence or (preview_required and not derivatives) or any(
                item.get("confidence") is not None and float(item["confidence"]) < 0.8
                for item in evidence
            )
            if attachment.get("scope") != "library":
                STORE.transition_attachment(
                    attachment["id"], "needs_review" if needs_review else "ready",
                    error_code="preview_unavailable" if preview_required and not derivatives else "",
                )
            STORE.complete_job(job["id"])
        except Exception as exc:
            code = str(exc) if str(exc) in {
                "ocr_backend_unavailable", "parse_timeout", "empty_parse_result",
                "library_vector_index_disabled", "attachment_vector_index_unavailable",
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


def _verify_scanner() -> None:
    temporary_dir = SETTINGS.data_dir / "temporary"
    temporary_dir.mkdir(parents=True, exist_ok=True)
    probe = temporary_dir / f"scanner_probe_{uuid4().hex}.txt"
    try:
        probe.write_bytes(b"CP2 attachment scanner readiness probe")
        scan_file(probe, SETTINGS.scanner_mode, SETTINGS.allow_fake_scanner)
    finally:
        probe.unlink(missing_ok=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global SCANNER_READY
    STOP.clear()
    validate_library_configuration(
        library_enabled=os.getenv("PERSONAL_LIBRARY_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
        vector_enabled=VECTOR_INDEX.enabled,
    )
    try:
        await asyncio.to_thread(_verify_scanner)
        SCANNER_READY = True
    except (ScannerUnavailable, MalwareDetected):
        SCANNER_READY = False
        LOGGER.error("attachment scanner readiness check failed")
    workers = [threading.Thread(target=_worker, daemon=True, name="attachment-parser")]
    if VECTOR_INDEX.enabled:
        workers.append(threading.Thread(target=_vector_worker, daemon=True, name="attachment-vector-index"))
    workers.append(threading.Thread(target=_cleanup, daemon=True, name="attachment-cleanup"))
    for worker in workers:
        worker.start()
    yield
    STOP.set()
    SCANNER_READY = False
    for worker in workers:
        worker.join(timeout=3)


app = FastAPI(title="CP2 Attachment Service", version="1.0.0", lifespan=lifespan)


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", dependencies=[Depends(_authorize)])
def ready() -> dict[str, Any]:
    if not SCANNER_READY:
        raise HTTPException(503, {"code": "scanner_unavailable"})
    return {"status": "ready", "vision_enabled": SETTINGS.vision_enabled, "scanner_ready": True}


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
        scan_file(temporary, SETTINGS.scanner_mode, SETTINGS.allow_fake_scanner)
        record = _persist_uploaded_file(
            temporary=temporary, attachment_id=attachment_id, filename=filename,
            mime_type=request.headers.get("content-type", ""), extension=validated.extension,
            size=size, sha256=digest.hexdigest(), owner_id=x_owner_id,
            dedupe_domain=x_dedupe_domain, scope=x_scope, expires_at=x_expires_at,
            status="scanning",
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
        STORE.transition_attachment(attachment_id, "parsing")
        STORE.enqueue(f"job_{uuid4().hex}", attachment_id, "parse")
        if x_scope == "library":
            LOGGER.info(
                "LIBRARY_UPLOAD owner_hash=%s knowledge_base_id=%s document_id=%s version_id=%s",
                hashlib.sha256(x_owner_id.encode()).hexdigest()[:12], x_knowledge_base_id,
                x_document_id, x_version_id,
            )
        return _public_record(STORE.get_attachment(attachment_id) or record)
    except AttachmentValidationError as exc:
        raise HTTPException(422, {"code": exc.code, "message": str(exc)}) from exc
    except MalwareDetected as exc:
        LOGGER.warning("malware quarantined attachment_id=%s hash=%s", attachment_id, digest.hexdigest()[:12])
        return _public_record(_persist_uploaded_file(
            temporary=temporary, attachment_id=attachment_id, filename=filename,
            mime_type=request.headers.get("content-type", ""), extension=validated.extension,
            size=size, sha256=digest.hexdigest(), owner_id=x_owner_id,
            dedupe_domain=x_dedupe_domain, scope=x_scope, expires_at=x_expires_at,
            status="quarantined", error_code="malware_detected",
        ))
    except ScannerUnavailable as exc:
        raise HTTPException(503, {"code": "scanner_unavailable", "message": str(exc)}) from exc
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
    _queue_vector_index(attachment_id)
    return {"items": updated}


@app.get("/v1/attachments/{attachment_id}/evidence/{evidence_id}/revisions", dependencies=[Depends(_authorize)])
def revisions(attachment_id: str, evidence_id: str) -> dict[str, Any]:
    if not STORE.get_attachment(attachment_id):
        raise HTTPException(404, "attachment not found")
    return {"items": STORE.list_revisions(attachment_id, evidence_id)}


@app.get("/v1/attachments/{attachment_id}/content", dependencies=[Depends(_authorize)])
def content(attachment_id: str) -> FileResponse:
    record = STORE.get_attachment(attachment_id)
    if not record or record["status"] in {"expired", "deleted", "quarantined"}:
        raise HTTPException(404, "attachment not found")
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
        try:
            _migrate_blob_domain(record, body.dedupe_domain)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    STORE.update_attachment(attachment_id, scope=body.scope, expires_at=body.expires_at)
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
    ready_ids = [attachment_id for attachment_id in body.attachment_ids if (record := STORE.get_attachment(attachment_id)) and record["status"] in {"ready", "needs_review"}]
    if not body.query.strip():
        items = STORE.list_evidence(ready_ids)[:body.top_k]
        for rank, item in enumerate(items, 1):
            item["score"] = max(0.01, 1.0 - (rank - 1) * 0.01)
        return {"items": items}
    lexical = STORE.search_evidence(ready_ids, body.query, body.top_k)
    vector = []
    if body.query_vector is not None:
        try:
            vector = VECTOR_INDEX.search_by_vector(ready_ids, body.query_vector, body.top_k)
        except Exception:
            vector = []
    by_id = {item["evidence_id"]: item for item in STORE.list_evidence(ready_ids)}
    scores: dict[str, float] = {}
    for rank, item in enumerate(lexical, 1):
        scores[item["evidence_id"]] = scores.get(item["evidence_id"], 0.0) + 1 / (60 + rank)
        by_id[item["evidence_id"]] = item
    for rank, item in enumerate(vector, 1):
        evidence_id = item.get("evidence_id")
        if evidence_id in by_id:
            scores[evidence_id] = scores.get(evidence_id, 0.0) + 1 / (60 + rank)
    items = []
    for evidence_id in sorted(scores, key=lambda value: (-scores[value], value))[:body.top_k]:
        item = dict(by_id[evidence_id])
        item["score"] = min(1.0, scores[evidence_id] * 30)
        items.append(item)
    return {"items": items}


@app.post("/v1/library/search", dependencies=[Depends(_authorize)])
def search_library(body: LibrarySearchRequest) -> dict[str, Any]:
    # owner/source/library/active are resolved before either FTS5 or Milvus
    # search. Unauthorized rows never enter a retrieval candidate set.
    versions = STORE.list_library_versions(
        body.owner_id,
        body.knowledge_base_id,
        document_ids=body.doc_ids,
        active_only=True,
    )
    attachment_ids = [str(item["id"]) for item in versions]
    vector_refs = [str(item.get("vector_ref") or item["id"]) for item in versions]
    vector_to_attachment = {
        str(item.get("vector_ref") or item["id"]): str(item["id"])
        for item in versions
    }
    candidate_k = max(body.top_k * 4, 20)
    lexical_rows = (
        STORE.search_evidence(attachment_ids, body.query, candidate_k)
        if body.mode in {"bm25", "hybrid"} else []
    )
    vector_rows: list[dict[str, Any]] = []
    vector_degraded = False
    if body.mode in {"vector", "hybrid"} and body.query_vector is not None:
        try:
            vector_rows = VECTOR_INDEX.search_by_vector(vector_refs, body.query_vector, candidate_k)
            for row in vector_rows:
                row["attachment_id"] = vector_to_attachment.get(str(row.get("attachment_id")), str(row.get("attachment_id")))
        except Exception as exc:
            vector_degraded = True
            LOGGER.warning(
                "LIBRARY_SEARCH vector degraded knowledge_base_id=%s error=%s",
                body.knowledge_base_id, exc.__class__.__name__,
            )
    evidence = {item["evidence_id"]: item for item in STORE.list_evidence(attachment_ids)}
    result = {"items": fuse_library_candidates(
        evidence, lexical_rows, vector_rows, mode=body.mode, top_k=body.top_k,
    )}
    if vector_degraded:
        result["degraded"] = ["vector"]
        if body.mode == "vector":
            result["error"] = "library_vector_unavailable"
    metadata = {str(item["id"]): item for item in versions}
    for item in result.get("items", []):
        version = metadata.get(str(item.get("attachment_id")), {})
        item.update({
            "knowledge_base_id": version.get("knowledge_base_id"),
            "document_id": version.get("document_id"),
            "version_id": version.get("version_id"),
            "source_scope": "personal",
            "filename": version.get("filename", item.get("filename")),
        })
    LOGGER.info(
        "LIBRARY_SEARCH owner_hash=%s knowledge_base_id=%s mode=%s candidates=%s results=%s",
        hashlib.sha256(body.owner_id.encode()).hexdigest()[:12],
        body.knowledge_base_id,
        body.mode,
        len(set(item.get("evidence_id") for item in (*lexical_rows, *vector_rows))),
        len(result["items"]),
    )
    return result


@app.post("/v1/attachments/{attachment_id}/inspect", dependencies=[Depends(_authorize)])
async def inspect(attachment_id: str, body: InspectRequest) -> dict[str, Any]:
    record = STORE.get_attachment(attachment_id)
    if not record:
        raise HTTPException(404, "attachment not found")
    if record["status"] not in {"ready", "needs_review"}:
        raise HTTPException(409, "attachment is not ready for inspection")
    if record["vision_status"] in {"queued", "running"}:
        raise HTTPException(503, {"code": "vision_busy"})
    if record["extension"] not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".pdf"}:
        raise HTTPException(422, "deep vision currently requires an image or PDF attachment")
    temporary = SETTINGS.data_dir / "temporary" / f"vision_source_{uuid4().hex}{record['extension']}"
    vision_image = SETTINGS.data_dir / "temporary" / f"vision_page_{uuid4().hex}.png"
    try:
        decrypt_file(Path(record["blob_path"]), temporary, SETTINGS.encryption_key, _blob_aad(record))
        try:
            locator = await asyncio.to_thread(
                _prepare_vision_image, temporary, record["extension"], body.page, body.bbox, vision_image,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        STORE.transition_vision(attachment_id, "queued")
        STORE.transition_vision(attachment_id, "running")
        answer = await asyncio.to_thread(VISION.inspect, vision_image, body.question)
        evidence_id = f"aev_{uuid4().hex}"
        STORE.add_evidence(attachment_id, {
            "evidence_id": evidence_id, "source_type": "vision_analysis",
            "content": answer, "locator": locator, "confidence": None,
            "parser": "qwen3-vl-2b-instruct",
        })
        _queue_vector_index(attachment_id)
        STORE.transition_vision(attachment_id, "ready")
        return {"attachment_id": attachment_id, "evidence_id": evidence_id, "content": answer, "source_type": "vision_analysis", "locator": locator, "version": 1, "confidence": None, "parser": "qwen3-vl-2b-instruct"}
    except RuntimeError as exc:
        code = str(exc) if str(exc) in {"vision_unavailable", "vision_busy"} else "vision_failed"
        STORE.transition_vision(attachment_id, "failed")
        raise HTTPException(503, {"code": code}) from exc
    finally:
        temporary.unlink(missing_ok=True)
        vision_image.unlink(missing_ok=True)
