from __future__ import annotations

import hashlib
from typing import Iterable, Protocol

from models.document import BlockType, Document, DocumentSection


class DocumentStructureProvider(Protocol):
    def build(self, document: Document) -> list[DocumentSection]: ...


def _id(version_id: str, path: Iterable[str]) -> str:
    joined = " / ".join(path)
    return "sec_" + hashlib.sha256(f"{version_id}:{joined}".encode("utf-8")).hexdigest()[:20]


def _summary(text: str, limit: int = 800) -> str:
    return " ".join(text.split())[:limit]


class NativeStructureProvider:
    """Build sections from parser-native heading and locator metadata."""

    def build(self, document: Document) -> list[DocumentSection]:
        return _build_native_sections(document)


def _build_native_sections(document: Document) -> list[DocumentSection]:
    version_id = document.version_id or f"legacy:{document.doc_id}"
    root_path = [document.title]
    all_chunk_ids = [chunk.chunk_id for chunk in document.chunks]
    pages = [
        int(block.locator["page"])
        for block in document.content_blocks
        if block.locator.get("page") is not None
    ]
    headings = [
        (index, block)
        for index, block in enumerate(document.content_blocks)
        if block.block_type == BlockType.HEADING and block.text.strip()
    ]
    rows = [DocumentSection(
        id=_id(version_id, root_path),
        version_id=version_id,
        title=document.title,
        section_path=root_path,
        page_start=min(pages) if pages else None,
        page_end=max(pages) if pages else None,
        summary=_summary(document.content),
        evidence_ids=all_chunk_ids,
        quality="high" if headings else "low",
    )]
    if not headings:
        return rows

    heading_chunk_starts: list[int] = []
    cursor = 0
    for _, heading in headings:
        found = next(
            (
                position for position, chunk in enumerate(document.chunks[cursor:], cursor)
                if heading.text.casefold() in chunk.text.casefold()
            ),
            cursor,
        )
        heading_chunk_starts.append(found)
        # Multiple headings may share a chunk. Keep the current position so each
        # section maps to that same authoritative Evidence row instead of being
        # forced onto an unrelated following chunk.
        cursor = min(found, len(document.chunks))

    stack: list[tuple[int, str]] = []
    for ordinal, ((block_start, heading), chunk_start) in enumerate(
        zip(headings, heading_chunk_starts), 1
    ):
        level = max(1, min(6, int(heading.level or 1)))
        stack = [entry for entry in stack if entry[0] < level]
        stack.append((level, heading.text.strip()))
        block_end = headings[ordinal][0] if ordinal < len(headings) else len(document.content_blocks)
        next_start = (
            heading_chunk_starts[ordinal]
            if ordinal < len(heading_chunk_starts)
            else len(document.chunks)
        )
        chunk_end = max(chunk_start + 1, next_start)
        section_blocks = document.content_blocks[block_start:block_end]
        section_chunks = document.chunks[chunk_start:chunk_end]
        section_pages = [
            int(block.locator["page"])
            for block in section_blocks
            if block.locator.get("page") is not None
        ]
        path = root_path + [entry[1] for entry in stack]
        rows.append(DocumentSection(
            id=_id(version_id, path),
            version_id=version_id,
            parent_id=_id(version_id, path[:-1]),
            level=len(path) - 1,
            title=heading.text.strip(),
            section_path=path,
            page_start=min(section_pages) if section_pages else heading.locator.get("slide"),
            page_end=max(section_pages) if section_pages else heading.locator.get("slide"),
            summary=_summary("\n".join(block.to_markdown() for block in section_blocks)),
            evidence_ids=[chunk.chunk_id for chunk in section_chunks],
            quality="high",
            ordinal=ordinal,
        ))
    return rows


def build_document_sections(
    document: Document,
    provider: DocumentStructureProvider | None = None,
) -> list[DocumentSection]:
    """Create deterministic, rebuildable navigation nodes from parsed structure."""
    return (provider or NativeStructureProvider()).build(document)
