from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Keep environment discovery stable when this module moves between layers.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class AttachmentSettings:
    internal_secret: str
    encryption_key: bytes
    encryption_key_id: str
    data_dir: Path
    max_image_bytes: int = 20 * 1024 * 1024
    max_document_bytes: int = 50 * 1024 * 1024
    max_pdf_pages: int = 200
    max_image_pixels: int = 40_000_000
    parse_timeout_seconds: int = 300
    worker_count: int = 1

    @classmethod
    def from_env(cls) -> "AttachmentSettings":
        raw_key = os.getenv("ATTACHMENT_ENCRYPTION_KEY", "")
        try:
            key = base64.urlsafe_b64decode(raw_key + "=" * (-len(raw_key) % 4))
        except Exception as exc:
            raise RuntimeError("ATTACHMENT_ENCRYPTION_KEY must be urlsafe base64") from exc
        if len(key) != 32:
            raise RuntimeError("ATTACHMENT_ENCRYPTION_KEY must decode to 32 bytes")
        secret = os.getenv("ATTACHMENT_INTERNAL_SECRET", "").strip()
        if not secret:
            raise RuntimeError("ATTACHMENT_INTERNAL_SECRET is required")
        root = Path(__file__).resolve().parents[2]
        return cls(
            internal_secret=secret,
            encryption_key=key,
            encryption_key_id=os.getenv("ATTACHMENT_ENCRYPTION_KEY_ID", "v1"),
            data_dir=Path(os.getenv(
                "ATTACHMENT_DATA_DIR",
                str(root / "data-persistence" / "data" / "attachments"),
            )).resolve(),
            max_image_bytes=_positive_int("ATTACHMENT_MAX_IMAGE_BYTES", 20 * 1024 * 1024),
            max_document_bytes=_positive_int("ATTACHMENT_MAX_DOCUMENT_BYTES", 50 * 1024 * 1024),
            max_pdf_pages=_positive_int("ATTACHMENT_MAX_PDF_PAGES", 200),
            max_image_pixels=_positive_int("ATTACHMENT_MAX_IMAGE_PIXELS", 40_000_000),
            parse_timeout_seconds=_positive_int("ATTACHMENT_PARSE_TIMEOUT_SECONDS", 300),
            worker_count=1,
        )


def validate_library_configuration(*, library_enabled: bool, vector_enabled: bool) -> None:
    if library_enabled and not vector_enabled:
        raise RuntimeError(
            "PERSONAL_LIBRARY_ENABLED=true requires "
            "ATTACHMENT_VECTOR_INDEX_ENABLED=true"
        )




def file_vector_collection() -> str | None:
    """Select an isolated destination without introducing another processing pipeline."""
    if os.getenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "false").lower() not in {"1", "true", "yes"}:
        return None
    collection = os.getenv("ATTACHMENT_MILVUS_COLLECTION", "attachment_evidence_cp2").strip()
    enterprise = os.getenv("MILVUS_COLLECTION", "doc_chunks").strip().casefold()
    sections = os.getenv("SECTION_MILVUS_COLLECTION", "document_sections_bgem3").strip().casefold()
    if not collection or collection.casefold() in {enterprise, sections}:
        raise RuntimeError("attachment_milvus_collection_must_be_isolated")
    return collection
