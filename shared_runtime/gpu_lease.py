from __future__ import annotations

import os
import time
from pathlib import Path


class GPULeaseUnavailable(RuntimeError):
    pass


class GPULease:
    """Cross-process exclusive GPU lease backed by an OS file lock."""

    def __init__(self, path: str | Path, timeout_seconds: float = 0.0):
        self.path = Path(path)
        self.timeout_seconds = timeout_seconds
        self._handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self._handle.write(b"0")
            self._handle.flush()
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                self._lock()
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    self._handle.close()
                    self._handle = None
                    raise GPULeaseUnavailable("gpu_busy")
                time.sleep(0.05)

    def __exit__(self, *_):
        if self._handle is not None:
            self._unlock()
            self._handle.close()
            self._handle = None

    def _lock(self) -> None:
        self._handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(self) -> None:
        self._handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
