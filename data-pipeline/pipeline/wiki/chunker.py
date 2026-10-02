"""Source-bound knowledge chunks for offline Wiki understanding.

These chunks are not retrieval Evidence. Each content span points back to an
active document-version Evidence chunk; citations continue to use Evidence.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from models.document import BlockType, Chunk, Document

from ..chunker import split_prose_at_boundaries


WIKI_CHUNKER_VERSION = "wiki-structure-v2-block-spans"


class WikiSourceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    evidence_start: int = Field(ge=0)
    evidence_end: int = Field(gt=0)
    chunk_start: int = Field(ge=0)
    chunk_end: int = Field(gt=0)
    block_start: int | None = None
    block_end: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    block_char_start: int | None = None
    block_char_end: int | None = None


class WikiChunk(BaseModel):
    """Versioned, non-overlapping understanding input with exact Evidence spans."""

    model_config = ConfigDict(extra="forbid")

    id: str
    document_id: str
    document_version_id: str
    section_id: str
    heading_path: list[str]
    content_type: str
    content: str
    source_spans: list[WikiSourceSpan]
    prev_chunk_id: str | None = None
    next_chunk_id: str | None = None


BoundaryReviewer = Callable[[str, list[str]], list[int]]


def section_for_evidence(document: Document, evidence: Chunk):
    """Resolve by the Evidence's own heading path, never an incidental ID overlap."""
    def key(path: list[str]) -> tuple[str, ...]:
        values = [" ".join(value.casefold().split()) for value in path]
        if values and values[0] == " ".join(document.title.casefold().split()):
            values = values[1:]
        return tuple(values)

    expected = key(evidence.section_path)
    candidates = [section for section in document.sections
                  if evidence.chunk_id in section.evidence_ids]
    exact = [section for section in candidates if key(section.section_path) == expected]
    if exact:
        return min(exact, key=lambda section: section.ordinal)
    roots = [section for section in candidates if section.level == 0]
    return min(roots, key=lambda section: section.ordinal) if roots else None


def _source_start(evidence: Chunk, heading: str) -> int:
    start = evidence.overlap_prefix_length
    if start < 0 or start > len(evidence.text):
        raise ValueError("invalid Evidence overlap prefix")
    prefix = evidence.text[start:]
    for marker in (f"# {heading}\n\n", f"**{heading}**\n\n"):
        if prefix.startswith(marker):
            start += len(marker)
            break
    else:
        match = re.match(r"#{1,6}\s+[^\n]+\n\n", prefix)
        if match and match.group().splitlines()[0].lstrip("# ").strip() == heading:
            start += match.end()
    return start


def _content_type(block) -> str:
    if block.block_type == BlockType.TABLE:
        return "table"
    if block.block_type == BlockType.LIST:
        return "list"
    if block.locator.get("code"):
        return "code"
    return "prose"


def _locator(document: Document, block_start: int | None, block_end: int | None) -> dict[str, int | None]:
    blocks = document.content_blocks
    selected = blocks[block_start:block_end + 1] if (
        block_start is not None and block_end is not None
        and 0 <= block_start <= block_end < len(blocks)
    ) else []
    def value(name: str, *, end: bool = False) -> int | None:
        candidates = [block.locator.get(name) for block in selected]
        values = [candidate for candidate in candidates if isinstance(candidate, int)]
        return (max(values) if end else min(values)) if values else None
    return {
        "block_start": block_start, "block_end": block_end,
        "line_start": value("line_start"), "line_end": value("line_end", end=True),
        "page_start": value("page_start"), "page_end": value("page_end", end=True),
        "block_char_start": value("char_start"),
        "block_char_end": value("char_end", end=True),
    }


def _evidence_segments(
    document: Document, evidence: Chunk, source_start: int,
) -> list[tuple[int, int, str, dict[str, int | None]]]:
    """Locate each rendered source block inside its Evidence without rewriting it."""
    blocks = document.content_blocks
    if (evidence.block_start is None or evidence.block_end is None
            or not 0 <= evidence.block_start <= evidence.block_end < len(blocks)):
        return [(source_start, len(evidence.text), "prose", _locator(document, None, None))]
    block_indices = [index for index in range(evidence.block_start, evidence.block_end + 1)
                     if blocks[index].block_type != BlockType.HEADING]
    if block_indices and source_start > evidence.overlap_prefix_length:
        first = block_indices[0]
        rendered_first = blocks[first].to_markdown()
        if evidence.text[evidence.overlap_prefix_length:source_start].startswith(rendered_first):
            block_indices.pop(0)
    if not block_indices:
        return []
    cursor = source_start
    segments: list[tuple[int, int, str, dict[str, int | None]]] = []
    for index in block_indices:
        block = blocks[index]
        rendered = block.to_markdown()
        if not rendered:
            continue
        found = evidence.text.find(rendered, cursor)
        if found < 0:
            # Oversized single blocks are already sliced at sentence boundaries
            # by Evidence chunking. Their Evidence text is a literal substring.
            if len(block_indices) == 1 and evidence.text[source_start:] in rendered:
                return [(source_start, len(evidence.text), _content_type(block),
                         _locator(document, index, index))]
            raise ValueError("Evidence cannot be mapped to its source blocks")
        if evidence.text[cursor:found].strip():
            raise ValueError(f"unmapped content between Evidence source blocks: {evidence.chunk_id} block {index}")
        segments.append((found, found + len(rendered), _content_type(block),
                         _locator(document, index, index)))
        cursor = found + len(rendered)
    if evidence.text[cursor:].strip():
        raise ValueError(f"unmapped Evidence suffix after source blocks: {evidence.chunk_id}")
    return segments


def _pieces(text: str, start: int, max_chars: int, *, atomic: bool) -> list[tuple[int, int]]:
    if atomic:
        return [(start, len(text))] if text[start:].strip() else []
    spans: list[tuple[int, int]] = []
    for match in re.finditer(r"[^\n]+(?:\n(?!\n)[^\n]+)*", text[start:]):
        paragraph_start = start + match.start()
        paragraph = match.group()
        offset = paragraph_start
        for part in split_prose_at_boundaries(paragraph, max_chars):
            left = len(part) - len(part.lstrip())
            right = len(part.rstrip())
            if right > left:
                spans.append((offset + left, offset + right))
            offset += len(part)
    return spans


def build_wiki_chunks(
    document: Document, *, max_chars: int = 1800,
    boundary_reviewer: BoundaryReviewer | None = None,
) -> list[WikiChunk]:
    """Build section-aware knowledge units without copying retrieval overlap.

    The optional reviewer may request cuts *only* at existing paragraph/Evidence
    boundaries. It cannot rewrite text or create unsourced spans.
    """
    if not document.version_id or max_chars <= 0:
        raise ValueError("document version and positive max_chars are required")
    if len({chunk.chunk_id for chunk in document.chunks}) != len(document.chunks):
        raise ValueError("duplicate Evidence IDs")
    output: list[WikiChunk] = []
    pending: list[tuple[Chunk, int, int, dict[str, int | None]]] = []
    pending_section = ""
    pending_heading: list[str] = []
    pending_type = ""
    pending_length = 0

    def flush() -> None:
        nonlocal pending, pending_length
        if not pending:
            return
        parts: list[str] = []
        spans: list[WikiSourceSpan] = []
        cursor = 0
        for evidence, start, end, locator in pending:
            if parts:
                parts.append("\n\n")
                cursor += 2
            body = evidence.text[start:end]
            parts.append(body)
            spans.append(WikiSourceSpan(
                evidence_id=evidence.chunk_id, evidence_start=start, evidence_end=end,
                chunk_start=cursor, chunk_end=cursor + len(body), **locator,
            ))
            cursor += len(body)
        content = "".join(parts)
        source_key = "|".join(f"{span.evidence_id}:{span.evidence_start}:{span.evidence_end}" for span in spans)
        digest = hashlib.sha256(f"{document.version_id}|{source_key}|{content}".encode()).hexdigest()[:24]
        output.append(WikiChunk(
            id=f"wc_{digest}", document_id=document.doc_id,
            document_version_id=document.version_id, section_id=pending_section,
            heading_path=list(pending_heading), content_type=pending_type,
            content=content, source_spans=spans,
        ))
        pending = []
        pending_length = 0

    for evidence in document.chunks:
        if not evidence.text.strip():
            continue
        section = section_for_evidence(document, evidence)
        section_id = section.id if section else ""
        heading_path = list(section.section_path) if section else list(evidence.section_path)
        # Evidence may have a greeting/presentation heading intentionally omitted
        # from SectionTree; strip its actual rendered heading, not the fallback root.
        source_start = _source_start(
            evidence, evidence.section_path[-1] if evidence.section_path else "",
        )
        for segment_start, segment_end, kind, locator in _evidence_segments(document, evidence, source_start):
            segment_text = evidence.text[:segment_end]
            for start, end in _pieces(segment_text, segment_start, max_chars, atomic=kind != "prose"):
                body = evidence.text[start:end]
                if not body.strip():
                    continue
                same_group = pending and pending_section == section_id and pending_type == kind
                too_large = pending_length + (2 if pending else 0) + len(body) > max_chars
                if (not same_group or too_large or kind != "prose") and pending:
                    flush()
                if not pending:
                    pending_section, pending_heading, pending_type = section_id, heading_path, kind
                pending.append((evidence, start, end, locator))
                pending_length += (2 if pending_length else 0) + len(body)
                if kind != "prose":
                    flush()
    flush()
    if boundary_reviewer:
        reviewed: list[WikiChunk] = []
        for chunk in output:
            if len(chunk.source_spans) <= 1:
                reviewed.append(chunk)
                continue
            proposed = boundary_reviewer(chunk.content, [
                chunk.content[span.chunk_start:span.chunk_end] for span in chunk.source_spans
            ])
            allowed = {span.chunk_end for span in chunk.source_spans[:-1]}
            if any(cut not in allowed for cut in proposed) or proposed != sorted(set(proposed)):
                raise ValueError("reviewer may only cut at existing source boundaries")
            if not proposed:
                reviewed.append(chunk)
                continue
            span_groups: list[list[WikiSourceSpan]] = [[]]
            for span in chunk.source_spans:
                span_groups[-1].append(span)
                if span.chunk_end in proposed:
                    span_groups.append([])
            evidence_by_id = {item.chunk_id: item for item in document.chunks}
            for group in span_groups:
                content_parts: list[str] = []
                source_spans: list[WikiSourceSpan] = []
                cursor = 0
                for span in group:
                    if content_parts:
                        content_parts.append("\n\n")
                        cursor += 2
                    body = evidence_by_id[span.evidence_id].text[span.evidence_start:span.evidence_end]
                    content_parts.append(body)
                    source_spans.append(span.model_copy(update={
                        "chunk_start": cursor, "chunk_end": cursor + len(body),
                    }))
                    cursor += len(body)
                content = "".join(content_parts)
                source_key = "|".join(
                    f"{span.evidence_id}:{span.evidence_start}:{span.evidence_end}"
                    for span in source_spans
                )
                digest = hashlib.sha256(
                    f"{document.version_id}|{source_key}|{content}".encode()
                ).hexdigest()[:24]
                reviewed.append(chunk.model_copy(update={
                    "id": f"wc_{digest}", "content": content,
                    "source_spans": source_spans,
                }))
        output = reviewed
    for index, chunk in enumerate(output):
        chunk.prev_chunk_id = output[index - 1].id if index else None
        chunk.next_chunk_id = output[index + 1].id if index + 1 < len(output) else None
    # Every substantive source character is represented exactly once. Heading
    # and retrieval-overlap prefixes are navigation/context, not Wiki content.
    by_evidence = {chunk.chunk_id: chunk for chunk in document.chunks}
    covered: dict[str, list[int]] = {
        chunk.chunk_id: [0] * len(chunk.text) for chunk in document.chunks
    }
    for wiki_chunk in output:
        for span in wiki_chunk.source_spans:
            evidence = by_evidence[span.evidence_id]
            if (wiki_chunk.content[span.chunk_start:span.chunk_end]
                    != evidence.text[span.evidence_start:span.evidence_end]):
                raise ValueError("Wiki chunk content is not an exact Evidence span")
            for position in range(span.evidence_start, span.evidence_end):
                covered[span.evidence_id][position] += 1
    for evidence in document.chunks:
        if not evidence.text.strip():
            continue
        section = section_for_evidence(document, evidence)
        heading_path = list(section.section_path) if section else list(evidence.section_path)
        source_start = _source_start(
            evidence, evidence.section_path[-1] if evidence.section_path else "",
        )
        for position in range(source_start, len(evidence.text)):
            if evidence.text[position].isspace():
                continue
            if covered[evidence.chunk_id][position] != 1:
                raise ValueError("Wiki source coverage is missing or duplicated")
    return output
