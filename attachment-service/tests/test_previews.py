from pathlib import Path
from subprocess import CompletedProcess

from PIL import Image

from attachment_service.crypto import decrypt_file
from attachment_service.previews import build_encrypted_previews
from attachment_service.office import remove_office_tree


def test_image_thumbnail_is_encrypted_and_decryptable(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (1000, 600), "white").save(source)
    key = b"p" * 32
    items = build_encrypted_previews(source, "att_preview", ".png", tmp_path / "data", key, "v1")
    assert len(items) == 1
    assert items[0]["kind"] == "thumbnail"
    encrypted = Path(items[0]["blob_path"])
    assert encrypted.read_bytes().startswith(b"CP2ATT01")
    output = tmp_path / "preview.webp"
    decrypt_file(encrypted, output, key, f"att_preview:{items[0]['id']}".encode())
    with Image.open(output) as image:
        assert image.width <= 512
        assert image.height <= 512


def test_pdf_builds_page_preview_with_locator(tmp_path: Path) -> None:
    import fitz
    source = tmp_path / "source.pdf"
    pdf = fitz.open()
    pdf.new_page()
    pdf.new_page()
    pdf.save(source)
    pdf.close()
    items = build_encrypted_previews(source, "att_pdf", ".pdf", tmp_path / "data", b"q" * 32, "v1")
    pages = [item for item in items if item["kind"] == "page"]
    assert [item["locator"]["page"] for item in pages] == [1, 2]


def test_pptx_uses_isolated_office_conversion_and_slide_locators(
    tmp_path: Path, monkeypatch,
) -> None:
    import fitz
    from attachment_service import previews

    source = tmp_path / "slides.pptx"
    source.write_bytes(b"test fixture placeholder")
    monkeypatch.setattr(previews, "resolve_libreoffice", lambda: "soffice")

    def convert(command, **kwargs):
        output_dir = Path(command[command.index("--outdir") + 1])
        pdf = fitz.open()
        pdf.new_page()
        pdf.new_page()
        pdf.save(output_dir / "slides.pdf")
        pdf.close()
        assert any(value.startswith("-env:UserInstallation=file:") for value in command)
        assert kwargs["timeout"] == 120
        return CompletedProcess(command, 0)

    monkeypatch.setattr(previews.subprocess, "run", convert)
    items = build_encrypted_previews(
        source, "att_slides", ".pptx", tmp_path / "data", b"r" * 32, "v1",
    )
    pages = [item for item in items if item["kind"] == "page"]
    assert [item["locator"] for item in pages] == [
        {"page": 1, "slide": 1}, {"page": 2, "slide": 2},
    ]
    assert not list((tmp_path / "data" / "temporary").glob("office_preview_*"))


def test_office_cleanup_handles_long_windows_paths(tmp_path: Path) -> None:
    target = tmp_path / "office_preview" / ("segment" * 10) / ("nested" * 10)
    target.mkdir(parents=True)
    (target / "cache.bin").write_bytes(b"cache")
    assert remove_office_tree(tmp_path / "office_preview") is True
    assert not (tmp_path / "office_preview").exists()
