"""Build source-bound classifier inputs without retrieval or semantic grading.

Callers supply a valid binding report and the SAME Evidence used for that report.
They must still recheck current access/version/hash before a model call. This
pure constructor is neither an authorization check nor a positive source grant.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Callable, Sequence


IDENTITY_FIELDS = (
    "source_type", "source_scope", "doc_id", "chunk_id", "evidence_ref",
    "content_hash", "source_version", "version_id", "attachment_id", "evidence_id",
)
CONTEXT_POLICY = "bound-structure.v1"


@dataclass(frozen=True)
class SourceSpan:
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class SourceContext:
    citation_id: int
    provenance: dict
    excerpt_sha256: str
    anchors: tuple[SourceSpan, ...]
    spans: tuple[SourceSpan, ...]
    text: str


@dataclass(frozen=True)
class VerificationInput:
    claim_id: str
    claim: str
    status: str
    reason: str
    sources: tuple[SourceContext, ...] = ()
    premise: str = ""
    input_tokens: int | None = None
    context_policy: str = CONTEXT_POLICY


@dataclass(frozen=True)
class _Block:
    kind: str
    start: int
    end: int
    level: int = 0
    rows: tuple[tuple[int, int], ...] = ()


def _cells(line: str) -> list[str] | None:
    """Markdown columns, excluding escaped pipes and inline-code pipes."""
    cells, pending, ticks = [], [], 0
    index = 0
    while index < len(line):
        char = line[index]
        if char == "\\" and index + 1 < len(line):
            pending.extend(line[index:index + 2])
            index += 2
            continue
        if char == "`":
            end = index + 1
            while end < len(line) and line[end] == "`":
                end += 1
            count = end - index
            ticks = count if not ticks else 0 if ticks == count else ticks
            pending.append(line[index:end])
            index = end
            continue
        if char == "|" and not ticks:
            cells.append("".join(pending).strip())
            pending = []
        else:
            pending.append(char)
        index += 1
    if not cells:
        return None
    cells.append("".join(pending).strip())
    if not cells[0]:
        cells.pop(0)
    if cells and not cells[-1]:
        cells.pop()
    return cells if len(cells) >= 2 else None


def _blocks(text: str) -> list[_Block]:
    lines = text.splitlines(keepends=True)
    starts, offset = [], 0
    for line in lines:
        starts.append(offset)
        offset += len(line)
    result = []
    index = 0

    def table_at(i):
        if i + 1 >= len(lines):
            return False
        header, separator = _cells(lines[i]), _cells(lines[i + 1])
        return bool(header and separator and len(header) == len(separator)
                    and all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator))

    def heading(i):
        match = re.match(r"^ {0,3}(#{1,6})\s+\S", lines[i])
        if match:
            return len(match[1]), 1
        if i + 1 < len(lines) and "|" not in lines[i]:
            underline = lines[i + 1].strip()
            if re.fullmatch(r"={3,}|-{3,}", underline):
                return (1 if underline[0] == "=" else 2), 2
        return None

    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        start = index
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})", lines[index])
        title = heading(index)
        if fence:
            marker = fence[1]
            index += 1
            while index < len(lines):
                closing = lines[index].strip()
                index += 1
                if re.fullmatch(re.escape(marker[0]) + "{" + str(len(marker)) + ",}", closing):
                    break
            kind, level, rows = "code", 0, ()
        elif title:
            index += title[1]
            kind, level, rows = "heading", title[0], ()
        elif re.match(r"^\s*<table\b", lines[index], re.I):
            index += 1
            while index < len(lines) and not re.search(r"</table\s*>", lines[index - 1], re.I):
                index += 1
            kind, level, rows = "html_table", 0, ()
        elif table_at(index):
            width = len(_cells(lines[index]))
            index += 2
            while index < len(lines):
                cells = _cells(lines[index])
                if cells is None or len(cells) != width:
                    break
                index += 1
            rows = tuple((starts[i], starts[i] + len(lines[i])) for i in range(start, index))
            kind, level = "table", 0
        else:
            index += 1
            while index < len(lines) and lines[index].strip() and not heading(index) and not table_at(index):
                if re.match(r"^ {0,3}(`{3,}|~{3,})|^\s*<table\b", lines[index], re.I):
                    break
                index += 1
            kind, level, rows = "paragraph", 0, ()
        result.append(_Block(kind, starts[start], starts[index - 1] + len(lines[index - 1]), level, rows))
    return result


def _intersects(start: int, end: int, span: tuple[int, int]) -> bool:
    return start < span[1] and span[0] < end


def _context(text: str, anchors: list[tuple[int, int]]) -> tuple[tuple[SourceSpan, ...], str]:
    blocks = _blocks(text)
    selected = []
    for index, block in enumerate(blocks):
        if not any(_intersects(block.start, block.end, anchor) for anchor in anchors):
            continue
        # Retain the enclosing heading path: scope, period, subject or units may
        # live here. Nothing is chosen by claim keywords or similarity scores.
        headings = []
        for previous in blocks[:index]:
            if previous.kind == "heading":
                while headings and headings[-1].level >= previous.level:
                    headings.pop()
                headings.append(previous)
        selected.extend((h.start, h.end) for h in headings)
        if block.kind != "table":
            if block.kind == "paragraph" and any(
                line.lstrip().startswith("|") and _cells(line)
                for line in text[block.start:block.end].splitlines()
            ):
                raise ValueError("table_structure_unavailable")
            selected.append((block.start, block.end))
            if block.kind not in {"html_table", "paragraph"}:
                continue
        else:
            selected.extend(block.rows[:2])  # Exact header and separator.
            rows = [row for row in block.rows[2:] if any(_intersects(*row, anchor) for anchor in anchors)]
            if not rows:
                raise ValueError("table_anchor_without_data_row")
            # Empty cells may inherit row labels or merged-cell context. Retain
            # the complete table rather than inventing an owner or unit.
            if any(any(not cell for cell in (_cells(text[a:b]) or [])) for a, b in rows):
                rows = list(block.rows[2:])
            selected.extend(rows)
        # Preserve contiguous prose scope/notes, including qualifications in
        # separate paragraphs. A heading/table/code boundary ends this envelope;
        # there is no claim-keyword filter or fixed-size neighbor window.
        for direction in (-1, 1):
            neighbor = index + direction
            while 0 <= neighbor < len(blocks) and blocks[neighbor].kind == "paragraph":
                selected.append((blocks[neighbor].start, blocks[neighbor].end))
                neighbor += direction
    merged = []
    for start, end in sorted(set(selected)):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    if not merged:
        raise ValueError("anchor_context_missing")
    spans = tuple(SourceSpan(start, end, text[start:end]) for start, end in merged)
    rendered = spans[0].text
    for previous, current in zip(spans, spans[1:]):
        gap = text[previous.end:current.start]
        rendered += (gap if not gap.strip() else "\n") + current.text
    return spans, rendered


def build_verification_inputs(
    binding: dict, evidence: Sequence, *, max_context_chars: int = 6000,
    token_counter: Callable[[str, str], int] | None = None, max_input_tokens: int = 512,
) -> list[VerificationInput]:
    """Consume binding output; never rewrite claims, search, truncate or grade.

    Offsets are local to each Evidence.content, not the parent document. The
    optional counter must count the classifier's COMPLETE serialized input,
    including EOS, claim and special tokens. Unusable input has no premise.
    """
    if binding.get("valid") is not True or binding.get("validation_kind") != "binding" or not binding.get("claims"):
        raise ValueError("valid_binding_report_required")
    if max_context_chars < 1 or max_input_tokens < 1:
        raise ValueError("positive_context_budgets_required")
    sources = [dict(item) if isinstance(item, dict) else item.model_dump() for item in evidence]
    results = []
    for claim in binding["claims"]:
        contexts, reason, tokens = [], "", None
        grouped = {}
        for support in claim["supports"]:
            citation = support.get("citation_id")
            if type(citation) is not int or not 1 <= citation <= len(sources):
                reason = "binding_reference_changed"
                break
            source = sources[citation - 1]
            if source.get("content_kind", "excerpt") != "excerpt" or support.get("image_region") is not None:
                reason = "text_context_unavailable"
                break
            if any(support.get(key) != source.get(key) for key in IDENTITY_FIELDS):
                reason = "binding_source_changed"
                break
            if (any(not source.get(key) for key in ("source_type", "doc_id", "chunk_id", "evidence_ref", "content_hash"))
                    or not (source.get("source_version") not in (None, "") or source.get("version_id"))):
                reason = "source_lineage_missing"
                break
            original = source.get("content", source.get("chunk_text", ""))
            start, end = support.get("source_start"), support.get("source_end")
            if (not isinstance(original, str) or type(start) is not int or type(end) is not int
                    or not 0 <= start < end <= len(original) or original[start:end] != support.get("quote")):
                reason = "binding_excerpt_changed"
                break
            grouped.setdefault(citation, []).append((start, end))
        if not claim["supports"]:
            reason = "binding_support_missing"
        if not reason:
            for citation, anchors in grouped.items():
                source = sources[citation - 1]
                original = source.get("content", source.get("chunk_text", ""))
                try:
                    spans, text = _context(original, anchors)
                except ValueError as exc:
                    reason = str(exc)
                    break
                contexts.append(SourceContext(
                    citation, {key: source.get(key) for key in IDENTITY_FIELDS},
                    hashlib.sha256(original.encode("utf-8")).hexdigest(),
                    tuple(SourceSpan(a, b, original[a:b]) for a, b in anchors), spans, text,
                ))
        premise = "\n\n".join(f"[Evidence {item.citation_id}]\n{item.text}" for item in contexts)
        if not reason and len(premise) > max_context_chars:
            reason = "context_budget_exceeded"
        if not reason and token_counter is not None:
            tokens = token_counter(premise, claim["text"])
            if type(tokens) is not int or tokens < 1:
                raise ValueError("invalid_input_token_count")
            if tokens > max_input_tokens:
                reason = "input_token_budget_exceeded"
        results.append(VerificationInput(
            claim["claim_id"], claim["text"], "needs_review" if reason else "ready", reason,
            tuple(contexts), "" if reason else premise, tokens,
        ))
    return results
