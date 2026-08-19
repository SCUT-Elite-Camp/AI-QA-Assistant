from __future__ import annotations

import gc
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .config import AttachmentSettings
from shared_runtime.gpu_lease import GPULease, GPULeaseUnavailable


LOGGER = logging.getLogger("attachment-service.vision")


class LocalVisionBackend:
    """Lazy local-only Qwen vision backend with a single GPU lease."""

    def __init__(self, settings: AttachmentSettings):
        self.settings = settings
        self._lease = threading.BoundedSemaphore(1)
        self._model: Any = None
        self._processor: Any = None
        self._last_used = 0.0

    def inspect(self, image_path: Path, question: str) -> str:
        if not self.settings.vision_enabled or not self.settings.vision_model_path:
            print("vision unavailable reason=configuration", file=sys.stderr, flush=True)
            raise RuntimeError("vision_unavailable")
        if os.name == "nt" and os.getenv("ATTACHMENT_VISION_CHILD") != "1":
            return self._inspect_isolated(image_path, question)
        return self._inspect_in_process(image_path, question)

    def _inspect_isolated(self, image_path: Path, question: str) -> str:
        """Keep native CUDA/quantization failures outside the API process."""
        if not self._lease.acquire(blocking=False):
            print("vision unavailable reason=local_lease_busy", file=sys.stderr, flush=True)
            raise RuntimeError("vision_busy")
        temporary_dir = self.settings.data_dir / "temporary"
        temporary_dir.mkdir(parents=True, exist_ok=True)
        request_path: Path | None = None
        result_path: Path | None = None
        try:
            # Attachment vector search lazily loads BGE-M3 in this API
            # process. Release that cache before Qwen starts so the Windows
            # commit limit can accommodate the isolated vision worker.
            try:
                from pipeline.embedder import release_local_model

                release_local_model()
            except (ImportError, RuntimeError):
                pass
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".json",
                prefix="vision_request_",
                dir=temporary_dir,
                delete=False,
            ) as request_file:
                json.dump(
                    {"image_path": str(image_path), "question": question},
                    request_file,
                    ensure_ascii=False,
                )
                request_path = Path(request_file.name)
            with NamedTemporaryFile(
                suffix=".json",
                prefix="vision_result_",
                dir=temporary_dir,
                delete=False,
            ) as result_file:
                result_path = Path(result_file.name)

            environment = os.environ.copy()
            environment["ATTACHMENT_VISION_CHILD"] = "1"
            timeout_seconds = max(
                1.0,
                float(os.getenv("ATTACHMENT_VISION_PROCESS_TIMEOUT_SECONDS", "85")),
            )
            try:
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "attachment_service.vision_worker",
                        str(request_path),
                        str(result_path),
                    ],
                    cwd=str(Path(__file__).resolve().parents[1]),
                    env=environment,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=timeout_seconds,
                    check=False,
                )
            except (subprocess.TimeoutExpired, OSError) as exc:
                LOGGER.warning("vision worker launch failed error_type=%s", exc.__class__.__name__)
                print(
                    f"vision worker launch failed error_type={exc.__class__.__name__}",
                    file=sys.stderr,
                    flush=True,
                )
                raise RuntimeError("vision_unavailable") from exc
            if not result_path.exists():
                LOGGER.warning("vision worker failed returncode=%s result=missing", completed.returncode)
                print(
                    f"vision worker failed returncode={completed.returncode} result=missing",
                    file=sys.stderr,
                    flush=True,
                )
                raise RuntimeError("vision_unavailable")
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError("vision_unavailable") from exc
            if completed.returncode != 0:
                LOGGER.warning(
                    "vision worker failed returncode=%s error_type=%s winerror=%s",
                    completed.returncode,
                    payload.get("error_type", "unknown"),
                    payload.get("winerror", "none"),
                )
                print(
                    "vision worker failed "
                    f"returncode={completed.returncode} "
                    f"error_type={payload.get('error_type', 'unknown')} "
                    f"winerror={payload.get('winerror', 'none')}",
                    file=sys.stderr,
                    flush=True,
                )
                raise RuntimeError(str(payload.get("error") or "vision_unavailable"))
            answer = str(payload.get("content") or "").strip()
            if not answer:
                raise RuntimeError(str(payload.get("error") or "vision_unavailable"))
            self._last_used = time.monotonic()
            return answer
        finally:
            if request_path is not None:
                request_path.unlink(missing_ok=True)
            if result_path is not None:
                result_path.unlink(missing_ok=True)
            self._lease.release()

    def _inspect_in_process(self, image_path: Path, question: str) -> str:
        if not self._lease.acquire(blocking=False):
            raise RuntimeError("vision_busy")
        try:
            lease_path = os.getenv("GPU_LEASE_PATH", str(self.settings.data_dir.parent / "gpu.lock"))
            try:
                lease = GPULease(lease_path, timeout_seconds=0)
                lease.__enter__()
            except GPULeaseUnavailable as exc:
                raise RuntimeError("vision_busy") from exc
            self._load()
            from PIL import Image
            image = Image.open(image_path).convert("RGB")
            messages = [{"role": "user", "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": question},
            ]}]
            inputs = self._processor.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_dict=True,
                return_tensors="pt",
            ).to(self._model.device)
            generated = self._model.generate(**inputs, max_new_tokens=512, do_sample=False)
            trimmed = generated[:, inputs["input_ids"].shape[1]:]
            self._last_used = time.monotonic()
            return self._processor.batch_decode(trimmed, skip_special_tokens=True)[0].strip()
        except RuntimeError as exc:
            if "out of memory" in str(exc).lower():
                self.unload()
                raise RuntimeError("vision_unavailable") from exc
            raise
        finally:
            if 'lease' in locals():
                lease.__exit__(None, None, None)
            self._lease.release()

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            import torch
            from transformers import AutoProcessor, BitsAndBytesConfig
            try:
                from transformers import AutoModelForMultimodalLM as VisionModelLoader
            except ImportError:
                from transformers import Qwen3VLForConditionalGeneration as VisionModelLoader
        except ImportError as exc:
            raise RuntimeError("vision_unavailable") from exc
        model_path = str(Path(self.settings.vision_model_path).resolve())
        quantization = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16)
        self._processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)
        self._model = VisionModelLoader.from_pretrained(
            model_path,
            local_files_only=True,
            quantization_config=quantization,
            device_map="cuda",
        )
        self._last_used = time.monotonic()

    def unload_if_idle(self, idle_seconds: int = 300) -> None:
        # The cleanup thread must never unload the processor/model while an
        # inference owns the single-request lease.
        if not self._lease.acquire(blocking=False):
            return
        try:
            if self._model is not None and time.monotonic() - self._last_used >= idle_seconds:
                self.unload()
        finally:
            self._lease.release()

    def unload(self) -> None:
        self._model = None
        self._processor = None
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
