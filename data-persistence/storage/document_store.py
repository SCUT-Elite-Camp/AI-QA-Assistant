import json
import os
import tempfile
from pathlib import Path

from data_persistence._paths import documents_dir

DOCS_DIR = str(documents_dir())


def _document_path(doc_id: str) -> Path:
    """Return a validated path for one document directly under DOCS_DIR."""
    if not isinstance(doc_id, str) or not doc_id:
        raise ValueError("doc_id must be a non-empty string")
    if any(character in doc_id for character in ("/", "\\", "\x00", ":")):
        raise ValueError("doc_id must be a single filename component")

    root = Path(DOCS_DIR).resolve()
    candidate = root / f"{doc_id}.json"
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ValueError("doc_id does not resolve to a safe document path") from exc

    if resolved.parent != root or candidate.is_symlink():
        raise ValueError("doc_id must resolve to a file directly under DOCS_DIR")
    return candidate


def save_document(doc_id: str, data: dict) -> None:
    """Atomically save a document as a JSON file in DOCS_DIR."""
    os.makedirs(DOCS_DIR, exist_ok=True)
    file_path = _document_path(doc_id)
    temp_path = None

    try:
        file_descriptor, temp_name = tempfile.mkstemp(
            dir=DOCS_DIR,
            prefix=".document-",
            suffix=".tmp",
        )
        temp_path = Path(temp_name)
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
        os.replace(temp_path, file_path)
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def load_document(doc_id: str) -> dict | None:
    """Load a JSON document from DOCS_DIR by its doc_id."""
    file_path = _document_path(doc_id)
    if not file_path.exists():
        return None

    with file_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def delete_document(doc_id: str) -> None:
    """Delete a document JSON file from DOCS_DIR."""
    file_path = _document_path(doc_id)
    if file_path.exists():
        file_path.unlink()


def list_documents() -> list[str]:
    """List all stored document IDs (without file extensions)."""
    if not os.path.isdir(DOCS_DIR):
        return []
    return [
        os.path.splitext(filename)[0]
        for filename in sorted(os.listdir(DOCS_DIR))
        if filename.endswith(".json") and filename != ".gitkeep"
    ]
