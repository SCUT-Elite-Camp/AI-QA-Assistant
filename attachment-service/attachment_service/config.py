from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path


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
    scanner_mode: str = "auto"
    allow_fake_scanner: bool = False
    vision_enabled: bool = False
    vision_model_path: str = ""

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
        production = os.getenv("NODE_ENV", "development").strip().lower() == "production"
        fake_scanner_requested = os.getenv(
            "ALLOW_FAKE_ATTACHMENT_SCANNER", "false"
        ).lower() in {"1", "true", "yes"}
        if production and fake_scanner_requested:
            raise RuntimeError("fake attachment scanner is forbidden in production")
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
            scanner_mode=os.getenv("ATTACHMENT_SCANNER", "auto").strip().lower(),
            allow_fake_scanner=fake_scanner_requested,
            vision_enabled=os.getenv("LOCAL_VISION_ENABLED", "false").lower() in {"1", "true", "yes"},
            vision_model_path=os.getenv("LOCAL_VISION_MODEL_PATH", "").strip(),
        )
