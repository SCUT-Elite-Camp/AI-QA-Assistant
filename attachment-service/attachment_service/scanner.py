from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class ScannerUnavailable(RuntimeError):
    pass


class MalwareDetected(RuntimeError):
    pass


def scan_file(path: Path, mode: str, allow_fake: bool) -> None:
    if mode == "disabled":
        if not allow_fake:
            raise ScannerUnavailable("disabled scanner is allowed only in development")
        return
    candidates = []
    program_files = os.getenv("ProgramFiles", "")
    program_data = os.getenv("ProgramData", "")
    if program_files:
        candidates.append(Path(program_files) / "Windows Defender" / "MpCmdRun.exe")
    if program_data:
        platform = Path(program_data) / "Microsoft" / "Windows Defender" / "Platform"
        if platform.exists():
            candidates.extend(sorted(platform.glob("*/MpCmdRun.exe"), reverse=True))
    executable = next((str(item) for item in candidates if item.exists()), None) or shutil.which("clamscan")
    if not executable:
        if allow_fake:
            return
        raise ScannerUnavailable("no supported malware scanner is available")
    args = [executable, "-Scan", "-ScanType", "3", "-File", str(path), "-DisableRemediation"] if "mpcmdrun" in executable.lower() else [executable, "--no-summary", str(path)]
    try:
        result = subprocess.run(args, capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ScannerUnavailable("malware scanner failed") from exc
    if result.returncode in {2, 3} or ("clamscan" in executable.lower() and result.returncode > 1):
        raise ScannerUnavailable("malware scanner failed")
    if result.returncode == 1:
        raise MalwareDetected("malware detected")
