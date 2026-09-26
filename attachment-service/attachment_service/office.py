from __future__ import annotations

import os
import shutil
import time
from pathlib import Path


def resolve_libreoffice() -> str | None:
    executable = os.getenv("LIBREOFFICE_PATH") or shutil.which("soffice") or shutil.which("libreoffice")
    if not executable:
        return None
    path = Path(executable)
    # On Windows soffice.exe may detach before soffice.bin releases its
    # temporary profile. The console launcher waits for conversion completion.
    if os.name == "nt" and path.suffix.lower() == ".exe":
        console_launcher = path.with_suffix(".com")
        if console_launcher.is_file():
            return str(console_launcher)
    return str(path)


def remove_office_tree(path: Path, attempts: int = 20) -> bool:
    target: str | Path = path
    if os.name == "nt":
        resolved = str(path.resolve())
        target = resolved if resolved.startswith("\\\\?\\") else f"\\\\?\\{resolved}"
    for attempt in range(attempts):
        shutil.rmtree(target, ignore_errors=True)
        if not path.exists():
            return True
        if attempt + 1 < attempts:
            time.sleep(0.1)
    return False
