from __future__ import annotations

import io
import subprocess
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from attachment_service.crypto import decrypt_file, encrypt_file
from attachment_service.validation import AttachmentValidationError, safe_filename, validate_file
from attachment_service.scanner import ScannerUnavailable, scan_file


def _png(path: Path) -> None:
    Image.new("RGB", (16, 16), "white").save(path, "PNG")


def test_aes_gcm_round_trip_and_tamper_detection(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    encrypted = tmp_path / "encrypted.bin"
    output = tmp_path / "output.bin"
    source.write_bytes(b"private enterprise content")
    encrypt_file(source, encrypted, b"k" * 32, b"att_1")
    decrypt_file(encrypted, output, b"k" * 32, b"att_1")
    assert output.read_bytes() == source.read_bytes()
    payload = bytearray(encrypted.read_bytes())
    payload[-1] ^= 1
    encrypted.write_bytes(payload)
    with pytest.raises(Exception):
        decrypt_file(encrypted, output, b"k" * 32, b"att_1")


def test_filename_path_traversal_is_removed() -> None:
    assert safe_filename(r"..\..\secret.png") == "secret.png"


def test_image_magic_and_pixel_validation(tmp_path: Path) -> None:
    image = tmp_path / "screen.png"
    _png(image)
    result = validate_file(image, "screen.png", "image/png", image.stat().st_size,
        max_image_bytes=1024 * 1024, max_document_bytes=1024 * 1024,
        max_pdf_pages=10, max_image_pixels=1000)
    assert result.category == "image"
    image.write_bytes(b"not-an-image")
    with pytest.raises(AttachmentValidationError, match="PNG"):
        validate_file(image, "screen.png", "image/png", image.stat().st_size,
            max_image_bytes=1024 * 1024, max_document_bytes=1024 * 1024,
            max_pdf_pages=10, max_image_pixels=1000)


def test_ooxml_macro_is_rejected(tmp_path: Path) -> None:
    document = tmp_path / "unsafe.docx"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr("word/vbaProject.bin", b"macro")
    with pytest.raises(AttachmentValidationError) as error:
        validate_file(document, document.name,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            document.stat().st_size, max_image_bytes=1_000_000,
            max_document_bytes=1_000_000, max_pdf_pages=10, max_image_pixels=1000)
    assert error.value.code == "macro_document"


def test_ooxml_extension_must_match_internal_content(tmp_path: Path) -> None:
    document = tmp_path / "renamed.docx"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
    with pytest.raises(AttachmentValidationError) as error:
        validate_file(document, document.name,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            document.stat().st_size, max_image_bytes=1_000_000,
            max_document_bytes=1_000_000, max_pdf_pages=10, max_image_pixels=1000)
    assert error.value.code == "magic_mismatch"


def test_text_magic_rejects_binary_nul_data(tmp_path: Path) -> None:
    document = tmp_path / "binary.txt"
    document.write_bytes(b"text\x00binary")
    with pytest.raises(AttachmentValidationError) as error:
        validate_file(document, document.name, "text/plain", document.stat().st_size,
            max_image_bytes=1_000_000, max_document_bytes=1_000_000,
            max_pdf_pages=10, max_image_pixels=1000)
    assert error.value.code == "magic_mismatch"


def test_scanner_timeout_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "safe.txt"
    target.write_text("safe", encoding="utf-8")
    monkeypatch.setattr("attachment_service.scanner.shutil.which", lambda _: "clamscan")

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("scanner", 120)

    monkeypatch.setattr("attachment_service.scanner.subprocess.run", timeout)
    with pytest.raises(ScannerUnavailable):
        scan_file(target, "auto", allow_fake=False)
