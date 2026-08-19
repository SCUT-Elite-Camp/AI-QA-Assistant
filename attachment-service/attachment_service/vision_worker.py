from __future__ import annotations

import json
import sys
from pathlib import Path

from .config import AttachmentSettings
from .vision import LocalVisionBackend


def main() -> int:
    if len(sys.argv) != 3:
        return 2
    request_path = Path(sys.argv[1])
    result_path = Path(sys.argv[2])
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        backend = LocalVisionBackend(AttachmentSettings.from_env())
        content = backend.inspect(
            Path(str(request["image_path"])),
            str(request["question"]),
        )
        payload = {"content": content}
        exit_code = 0
    except Exception as exc:
        code = str(exc)
        payload = {
            "error": code
            if code in {"vision_unavailable", "vision_busy"}
            else "vision_failed",
            "error_type": exc.__class__.__name__,
            "winerror": getattr(exc, "winerror", None),
        }
        exit_code = 1
    result_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
