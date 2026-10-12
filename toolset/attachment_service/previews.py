from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, ImageOps

from .crypto import encrypt_file
from .office import remove_office_tree, resolve_libreoffice


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
OFFICE_EXTENSIONS = {".doc", ".docx", ".ppt", ".pptx"}


def _convert_office_to_pdf(source: Path, temporary_dir: Path) -> tuple[Path, Path] | None:
    executable = resolve_libreoffice()
    if not executable:
        return None
    workdir = temporary_dir / f"office_preview_{uuid4().hex}"
    output_dir = workdir / "output"
    profile_dir = workdir / "profile"
    output_dir.mkdir(parents=True)
    profile_dir.mkdir()
    try:
        result = subprocess.run(
            [
                executable,
                "--headless", "--nologo", "--nodefault", "--nofirststartwizard",
                "--nolockcheck", "--norestore",
                f"-env:UserInstallation={profile_dir.resolve().as_uri()}",
                "--convert-to", "pdf", "--outdir", str(output_dir), str(source),
            ],
            capture_output=True,
            check=False,
            timeout=120,
        )
        converted = output_dir / f"{source.stem}.pdf"
        if result.returncode != 0 or not converted.is_file():
            remove_office_tree(workdir)
            return None
        return converted, workdir
    except (OSError, subprocess.TimeoutExpired):
        remove_office_tree(workdir)
        return None


def build_encrypted_previews(
    source: Path, attachment_id: str, extension: str, data_dir: Path,
    encryption_key: bytes, key_id: str,
) -> list[dict[str, Any]]:
    temporary_dir = data_dir / "temporary"
    temporary_dir.mkdir(parents=True, exist_ok=True)
    derivatives: list[dict[str, Any]] = []

    def persist(image: Image.Image, kind: str, locator: dict[str, Any]) -> None:
        derivative_id = f"der_{uuid4().hex}"
        plain = temporary_dir / f"{derivative_id}.webp"
        encrypted = data_dir / "derivatives" / attachment_id[4:6] / f"{derivative_id}.blob"
        normalized = image.convert("RGB")
        if kind == "thumbnail":
            normalized.thumbnail((512, 512))
        normalized.save(plain, "WEBP", quality=82, method=4)
        try:
            encrypt_file(plain, encrypted, encryption_key, f"{attachment_id}:{derivative_id}".encode())
        finally:
            plain.unlink(missing_ok=True)
        derivatives.append({
            "id": derivative_id, "kind": kind, "locator": locator,
            "mime_type": "image/webp", "blob_path": str(encrypted), "key_id": key_id,
        })

    try:
        if extension in IMAGE_EXTENSIONS:
            with Image.open(source) as image:
                persist(ImageOps.exif_transpose(image), "thumbnail", {})
            return derivatives

        preview_source = source
        office_workdir: Path | None = None
        if extension in OFFICE_EXTENSIONS:
            conversion = _convert_office_to_pdf(source, temporary_dir)
            if conversion is None:
                return derivatives
            preview_source, office_workdir = conversion

        if extension == ".pdf" or extension in OFFICE_EXTENSIONS:
            import fitz
            try:
                with fitz.open(preview_source) as pdf:
                    locator_key = "slide" if extension in {".ppt", ".pptx"} else "page"
                    if pdf.page_count:
                        first = pdf[0].get_pixmap(matrix=fitz.Matrix(0.75, 0.75), alpha=False)
                        locator = {"page": 1, **({"slide": 1} if locator_key == "slide" else {})}
                        persist(Image.frombytes("RGB", (first.width, first.height), first.samples), "thumbnail", locator)
                    for page_number, page in enumerate(pdf, 1):
                        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.25, 1.25), alpha=False)
                        locator = {"page": page_number, **({"slide": page_number} if locator_key == "slide" else {})}
                        persist(Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples), "page", locator)
            finally:
                if office_workdir is not None and not remove_office_tree(office_workdir):
                    raise RuntimeError("office_preview_cleanup_failed")
        return derivatives
    except Exception:
        for derivative in derivatives:
            Path(derivative["blob_path"]).unlink(missing_ok=True)
        raise
