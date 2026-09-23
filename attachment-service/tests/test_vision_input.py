from pathlib import Path
import json
import sys
from types import SimpleNamespace

import fitz
import pytest
from PIL import Image

from attachment_service.config import AttachmentSettings
from attachment_service.vision import LocalVisionBackend


def test_prepare_vision_image_renders_requested_pdf_page_and_crop(tmp_path: Path) -> None:
    from attachment_service.app import _prepare_vision_image

    source = tmp_path / "source.pdf"
    document = fitz.open()
    document.new_page(width=120, height=80)
    page = document.new_page(width=200, height=100)
    page.insert_text((20, 30), "SECOND PAGE")
    document.save(source)
    document.close()

    output = tmp_path / "page.png"
    locator = _prepare_vision_image(source, ".pdf", 2, [0.0, 0.0, 0.5, 1.0], output)
    with Image.open(output) as image:
        assert image.width == 200
        assert image.height == 200
    assert locator == {"page": 2, "bbox": [0.0, 0.0, 0.5, 1.0]}


def test_prepare_vision_image_rejects_invalid_locator(tmp_path: Path) -> None:
    from attachment_service.app import _prepare_vision_image

    source = tmp_path / "source.png"
    Image.new("RGB", (20, 20), "white").save(source)
    with pytest.raises(ValueError, match="invalid_bbox"):
        _prepare_vision_image(source, ".png", None, [0.8, 0.1, 0.2, 0.9], tmp_path / "out.png")
    with pytest.raises(ValueError, match="page_out_of_range"):
        _prepare_vision_image(source, ".png", 2, None, tmp_path / "out.png")


def test_vision_model_load_is_local_quantized_and_does_not_run_remote_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_path = tmp_path / "qwen"
    model_path.mkdir()
    captured = {}

    class Loader:
        @classmethod
        def from_pretrained(cls, path, **kwargs):
            captured[cls.__name__] = {"path": path, **kwargs}
            return object()

    class AutoProcessor(Loader):
        pass

    class AutoModelForMultimodalLM(Loader):
        pass

    class BitsAndBytesConfig:
        def __init__(self, **kwargs):
            captured["quantization"] = kwargs

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(float16="float16"))
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(
        AutoModelForMultimodalLM=AutoModelForMultimodalLM,
        AutoProcessor=AutoProcessor,
        BitsAndBytesConfig=BitsAndBytesConfig,
    ))
    settings = AttachmentSettings(
        internal_secret="secret", encryption_key=b"k" * 32, encryption_key_id="v1",
        data_dir=tmp_path / "data", vision_enabled=True, vision_model_path=str(model_path),
    )
    backend = LocalVisionBackend(settings)
    backend._load()
    processor = captured["AutoProcessor"]
    model = captured["AutoModelForMultimodalLM"]
    assert processor["local_files_only"] is True
    assert "trust_remote_code" not in processor
    assert model["local_files_only"] is True
    assert model["device_map"] == "cuda"
    assert "trust_remote_code" not in model
    assert captured["quantization"] == {
        "load_in_4bit": True, "bnb_4bit_compute_dtype": "float16",
    }
    assert backend._last_used > 0


def test_idle_cleanup_does_not_unload_during_inference(tmp_path: Path) -> None:
    settings = AttachmentSettings(
        internal_secret="secret", encryption_key=b"k" * 32, encryption_key_id="v1",
        data_dir=tmp_path / "data", vision_enabled=True, vision_model_path=str(tmp_path / "qwen"),
    )
    backend = LocalVisionBackend(settings)
    backend._model = object()
    backend._processor = object()
    backend._last_used = 0

    assert backend._lease.acquire(blocking=False)
    try:
        backend.unload_if_idle(idle_seconds=0)
        assert backend._model is not None
        assert backend._processor is not None
    finally:
        backend._lease.release()


def test_isolated_vision_worker_failure_keeps_parent_backend_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = AttachmentSettings(
        internal_secret="secret", encryption_key=b"k" * 32, encryption_key_id="v1",
        data_dir=tmp_path / "data", vision_enabled=True,
        vision_model_path=str(tmp_path / "qwen"),
    )
    backend = LocalVisionBackend(settings)
    image = tmp_path / "image.png"
    Image.new("RGB", (20, 20), "white").save(image)

    def crashed_worker(command, **kwargs):
        result_path = Path(command[-1])
        result_path.write_text(json.dumps({"error": "vision_unavailable"}), encoding="utf-8")
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr("attachment_service.vision.subprocess.run", crashed_worker)

    with pytest.raises(RuntimeError, match="vision_unavailable"):
        backend._inspect_isolated(image, "识别内容")

    assert backend._lease.acquire(blocking=False)
    backend._lease.release()
    assert list((settings.data_dir / "temporary").glob("vision_*.json")) == []
