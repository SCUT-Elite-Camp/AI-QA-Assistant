from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path
from typing import Any


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def _shared_chunk_text():
    """Load the repository's canonical chunker without copying its algorithm."""
    try:
        return importlib.import_module("pipeline.chunker").chunk_text
    except ModuleNotFoundError:
        pipeline_root = Path(__file__).resolve().parents[2] / "data-pipeline"
        if not pipeline_root.is_dir():
            raise RuntimeError("shared_chunker_unavailable") from None
        path = str(pipeline_root)
        if path not in sys.path:
            sys.path.insert(0, path)
        return importlib.import_module("pipeline.chunker").chunk_text


def _markdown_sections(text: str) -> list[tuple[str, int, int, list[str]]]:
    matches = list(_HEADING.finditer(text))
    if not matches:
        return [(text, 0, len(text), [])]

    sections: list[tuple[str, int, int, list[str]]] = []
    heading_stack: list[tuple[int, str]] = []
    if matches[0].start() > 0 and text[: matches[0].start()].strip():
        sections.append((text[: matches[0].start()], 0, matches[0].start(), []))
    for index, match in enumerate(matches):
        level = len(match.group(1))
        title = match.group(2).strip()
        heading_stack = [entry for entry in heading_stack if entry[0] < level]
        heading_stack.append((level, title))
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append((text[match.start():end], match.start(), end, [item[1] for item in heading_stack]))
    return sections


def chunk_attachment_evidence(
    evidence: list[dict[str, Any]],
    version_id: str,
    extension: str,
    *,
    chunk_size: int = 1200,
    overlap: int = 150,
) -> list[dict[str, Any]]:
    """Convert parsed evidence into stable, locator-preserving library chunks."""
    chunk_text = _shared_chunk_text()
    output: list[dict[str, Any]] = []

    def append_chunk(item: dict[str, Any], content: str, locator: dict[str, Any]) -> None:
        chunk_index = len(output)
        output.append({
            **item,
            "evidence_id": f"{version_id}_chunk_{chunk_index}",
            "content": content.strip(),
            "locator": {**locator, "chunk_index": chunk_index},
        })

    for item in evidence:
        content = str(item.get("content") or "")
        if not content.strip():
            continue
        base_locator = dict(item.get("locator") or {})
        # Tables, slides and already-small structured blocks retain their semantic unit.
        if item.get("source_type") == "table" or len(content) <= chunk_size:
            append_chunk(item, content, base_locator)
            continue

        sections = _markdown_sections(content) if extension == ".md" else [(content, 0, len(content), [])]
        for section_text, section_start, _, section_path in sections:
            for chunk in chunk_text(
                section_text,
                doc_id=version_id,
                chunk_size=chunk_size,
                overlap=overlap,
            ):
                relative_start = chunk.index * (chunk_size - overlap)
                absolute_start = section_start + relative_start
                locator = {
                    **base_locator,
                    "char_start": absolute_start,
                    "char_end": absolute_start + len(chunk.text),
                }
                if section_path:
                    locator["section_path"] = section_path
                append_chunk(item, chunk.text, locator)
    return output
