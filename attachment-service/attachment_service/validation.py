from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".html", ".htm"}
DATA_EXTENSIONS = {".xls", ".xlsx", ".csv", ".txt", ".md", ".json"}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | DOCUMENT_EXTENSIONS | DATA_EXTENSIONS
REJECTED_EXTENSIONS = {".docm", ".xlsm", ".pptm", ".zip", ".rar", ".7z"}

MIME_BY_EXTENSION = {
    ".png": {"image/png"}, ".jpg": {"image/jpeg"}, ".jpeg": {"image/jpeg"},
    ".webp": {"image/webp"}, ".bmp": {"image/bmp", "image/x-ms-bmp"},
    ".tif": {"image/tiff"}, ".tiff": {"image/tiff"},
    ".pdf": {"application/pdf"},
    ".doc": {"application/msword", "application/octet-stream"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".ppt": {"application/vnd.ms-powerpoint", "application/octet-stream"},
    ".pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    ".xls": {"application/vnd.ms-excel", "application/octet-stream"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".html": {"text/html"}, ".htm": {"text/html"}, ".csv": {"text/csv", "text/plain"},
    ".txt": {"text/plain"}, ".md": {"text/markdown", "text/plain"},
    ".json": {"application/json", "text/json", "text/plain"},
}


class AttachmentValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ValidatedFile:
    extension: str
    category: str


def safe_filename(value: str) -> str:
    name = Path(value.replace("\\", "/")).name.strip()
    name = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", name)[:255]
    if not name or name in {".", ".."}:
        raise AttachmentValidationError("invalid_filename", "invalid filename")
    return name


def validate_file(path: Path, filename: str, mime: str, size: int, *, max_image_bytes: int,
                  max_document_bytes: int, max_pdf_pages: int, max_image_pixels: int) -> ValidatedFile:
    extension = Path(filename).suffix.lower()
    if extension in REJECTED_EXTENSIONS or extension not in SUPPORTED_EXTENSIONS:
        raise AttachmentValidationError("unsupported_file_type", f"unsupported extension: {extension}")
    expected = MIME_BY_EXTENSION.get(extension, set())
    normalized_mime = mime.split(";", 1)[0].strip().lower()
    if expected and normalized_mime not in expected:
        raise AttachmentValidationError("mime_mismatch", "declared MIME does not match extension")
    category = "image" if extension in IMAGE_EXTENSIONS else "document"
    limit = max_image_bytes if category == "image" else max_document_bytes
    if size <= 0 or size > limit:
        raise AttachmentValidationError("file_too_large", "file exceeds configured size limit")
    with path.open("rb") as source:
        head = source.read(16)
    if extension == ".pdf" and not head.startswith(b"%PDF-"):
        raise AttachmentValidationError("magic_mismatch", "invalid PDF signature")
    if extension == ".png" and not head.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AttachmentValidationError("magic_mismatch", "invalid PNG signature")
    if extension in {".jpg", ".jpeg"} and not head.startswith(b"\xff\xd8\xff"):
        raise AttachmentValidationError("magic_mismatch", "invalid JPEG signature")
    if extension == ".webp" and not (head.startswith(b"RIFF") and head[8:12] == b"WEBP"):
        raise AttachmentValidationError("magic_mismatch", "invalid WebP signature")
    if extension == ".bmp" and not head.startswith(b"BM"):
        raise AttachmentValidationError("magic_mismatch", "invalid BMP signature")
    if extension in {".tif", ".tiff"} and not (head.startswith(b"II*\x00") or head.startswith(b"MM\x00*")):
        raise AttachmentValidationError("magic_mismatch", "invalid TIFF signature")
    if extension in {".doc", ".ppt", ".xls"}:
        if not head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            raise AttachmentValidationError("magic_mismatch", "invalid legacy Office signature")
        import olefile
        try:
            with olefile.OleFileIO(path) as container:
                streams = ["/".join(part).casefold() for part in container.listdir()]
                if any("encryptedpackage" in stream or "encryptioninfo" in stream for stream in streams):
                    raise AttachmentValidationError("encrypted_document", "encrypted Office documents are rejected")
                if any("vba" in stream or "_vba_project_cur" in stream for stream in streams):
                    raise AttachmentValidationError("macro_document", "macro-enabled documents are rejected")
        except AttachmentValidationError:
            raise
        except Exception as exc:
            raise AttachmentValidationError("invalid_office", "legacy Office container cannot be decoded") from exc
    if extension in {".docx", ".pptx", ".xlsx"}:
        if not zipfile.is_zipfile(path):
            raise AttachmentValidationError("magic_mismatch", "invalid OOXML container")
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            total = sum(item.file_size for item in infos)
            compressed = max(sum(item.compress_size for item in infos), 1)
            if len(infos) > 10_000 or total > 500 * 1024 * 1024 or total / compressed > 100:
                raise AttachmentValidationError("archive_bomb", "OOXML expansion limit exceeded")
            if any(item.filename.lower().endswith("vbaproject.bin") for item in infos):
                raise AttachmentValidationError("macro_document", "macro-enabled documents are rejected")
            required_part = {
                ".docx": "word/document.xml",
                ".pptx": "ppt/presentation.xml",
                ".xlsx": "xl/workbook.xml",
            }[extension]
            normalized_names = {item.filename.replace("\\", "/").lower() for item in infos}
            if required_part not in normalized_names or "[content_types].xml" not in normalized_names:
                raise AttachmentValidationError("magic_mismatch", "OOXML content does not match extension")
    if extension in {".csv", ".txt", ".md", ".json", ".html", ".htm"}:
        with path.open("rb") as source:
            sample = source.read(8192)
        if b"\x00" in sample:
            raise AttachmentValidationError("magic_mismatch", "text attachment contains binary data")
    if category == "image":
        previous_pixel_limit = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = max_image_pixels
        try:
            with Image.open(path) as image:
                total_pixels = image.width * image.height * int(getattr(image, "n_frames", 1))
                if total_pixels > max_image_pixels:
                    raise AttachmentValidationError("image_too_large", "image pixel limit exceeded")
                image.verify()
        except AttachmentValidationError:
            raise
        except Exception as exc:
            raise AttachmentValidationError("invalid_image", "image cannot be decoded") from exc
        finally:
            Image.MAX_IMAGE_PIXELS = previous_pixel_limit
    if extension == ".pdf":
        import fitz
        try:
            with fitz.open(path) as pdf:
                if pdf.needs_pass:
                    raise AttachmentValidationError("encrypted_document", "encrypted PDFs are rejected")
                if pdf.page_count > max_pdf_pages:
                    raise AttachmentValidationError("too_many_pages", "PDF page limit exceeded")
        except AttachmentValidationError:
            raise
        except Exception as exc:
            raise AttachmentValidationError("invalid_pdf", "PDF cannot be decoded") from exc
    return ValidatedFile(extension=extension, category=category)
