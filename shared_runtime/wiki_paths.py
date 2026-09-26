"""Resolve the shared Wiki database path independently of service working directories."""

from __future__ import annotations

import os
from pathlib import Path


def resolve_wiki_db_path(project_root: Path) -> Path:
    configured = os.getenv("WIKI_DB_PATH", "").strip()
    if not configured:
        return project_root / "data-persistence" / "data" / "wiki.sqlite3"
    path = Path(configured)
    return path if path.is_absolute() else project_root / path
