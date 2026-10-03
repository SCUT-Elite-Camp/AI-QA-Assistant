"""Private, side-effect-free filesystem layout for persistence backends."""

from pathlib import Path


_PERSISTENCE_ROOT = Path(__file__).resolve().parent.parent
_DATA_ROOT = _PERSISTENCE_ROOT / "data"


def data_dir() -> Path:
    """Return the shared persistence data directory without creating it."""
    return _DATA_ROOT


def documents_dir() -> Path:
    """Return the default document projection directory."""
    return data_dir() / "documents"


def chat_history_db_path() -> Path:
    """Return the default chat history SQLite path."""
    return data_dir() / "chat_history.db"


def topics_dir() -> Path:
    """Return the default topic storage directory."""
    return data_dir() / "topics"
