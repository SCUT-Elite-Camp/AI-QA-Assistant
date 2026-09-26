from __future__ import annotations

import multiprocessing
import queue
import time
from pathlib import Path
from typing import Any


def _parse_entry(result_queue: Any, path: str, attachment_id: str, extension: str) -> None:
    try:
        from .parsers import parse_attachment
        result_queue.put(("ok", parse_attachment(Path(path), attachment_id, extension)))
    except BaseException as exc:
        result_queue.put(("error", str(exc) or exc.__class__.__name__))


def parse_with_timeout(path: Path, attachment_id: str, extension: str, timeout_seconds: int) -> list[dict[str, Any]]:
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue(maxsize=1)
    process = context.Process(
        target=_parse_entry,
        args=(result_queue, str(path), attachment_id, extension),
        name=f"attachment-parse-{attachment_id[-12:]}",
        daemon=True,
    )
    process.start()
    deadline = time.monotonic() + timeout_seconds
    try:
        while time.monotonic() < deadline:
            try:
                status, payload = result_queue.get(timeout=min(0.2, max(0.01, deadline - time.monotonic())))
                process.join(timeout=1)
                if status == "ok":
                    return payload
                raise RuntimeError(str(payload))
            except queue.Empty:
                if not process.is_alive():
                    raise RuntimeError(f"parser_process_failed:{process.exitcode}")
        raise TimeoutError("parse_timeout")
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=3)
        result_queue.close()
        result_queue.join_thread()
