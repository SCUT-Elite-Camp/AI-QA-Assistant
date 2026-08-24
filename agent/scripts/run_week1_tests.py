from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the CP2 Week 1 Agent test gate")
    parser.add_argument("--collect-only", action="store_true")
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[2]
    command = [sys.executable, "-m", "pytest", "agent/tests"]
    if args.collect_only:
        command.append("--collect-only")
    return subprocess.call(command, cwd=project_root)


if __name__ == "__main__":
    raise SystemExit(main())

