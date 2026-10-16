"""Upload adapter: Pipeline parses; Data Persistence saves and schedules ingestion."""
from pathlib import Path
from typing import Any


def parse_attachment_context(path: Path, source_id: str, store: Any, *, timeout: int = 300) -> dict:
    from pipeline.files.parse_runner import parse_with_timeout

    parsed = parse_with_timeout(path, source_id, timeout)
    store.save_parsed_document(source_id, parsed)
    return {"context": parsed["context"], "items": parsed["items"]}
