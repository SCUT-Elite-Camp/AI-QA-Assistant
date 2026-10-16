"""Private, side-effect-free filesystem layout for persistence backends."""

from pathlib import Path
import os


_PERSISTENCE_ROOT = Path(__file__).resolve().parent.parent
_DATA_ROOT = _PERSISTENCE_ROOT / "data"


def data_dir() -> Path:
    """Return the shared persistence data directory without creating it."""
    return Path(os.getenv('AI_QA_DATA_DIR', str(_DATA_ROOT))).resolve()


def documents_dir() -> Path:
    """Share the configured projections across ingestion, retrieval and access checks."""
    configured = os.getenv('RESEARCH_DOCUMENTS_DIR', '').strip()
    return Path(configured).resolve() if configured else data_dir() / "documents"


def chat_history_db_path() -> Path:
    """Return the default chat history SQLite path."""
    return data_dir() / "chat_history.db"


def topics_dir() -> Path:
    """Return the default topic storage directory."""
    return Path(os.getenv('TOPICS_DATA_DIR', str(data_dir() / 'topics'))).resolve()


def resolve_wiki_db_path(project_root: Path) -> Path:
    configured = os.getenv("WIKI_DB_PATH", "").strip()
    if not configured:
        return project_root / "data-persistence" / "data" / "wiki.sqlite3"
    path = Path(configured)
    return path if path.is_absolute() else project_root / path
