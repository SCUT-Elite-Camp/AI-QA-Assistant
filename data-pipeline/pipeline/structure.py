from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Iterable, Protocol

from models.document import BlockType, ContentBlock, Document, DocumentSection
from shared_runtime.document_sections import normalize_section, stable_section_id


class DocumentStructureProvider(Protocol):
    def build(self, document: Document) -> list[DocumentSection]: ...


def _id(version_id: str, path: Iterable[str], ordinal: int = 0) -> str:
    return stable_section_id(version_id, path, ordinal)


def _normalise(text: str) -> str:
    return " ".join(text.split()).strip()


def _title_key(text: str) -> str:
    return " ".join(re.findall(r"\w+", _normalise(text).casefold(), flags=re.UNICODE))


def _is_non_navigable_heading(index: int, block: ContentBlock) -> bool:
    if index > 8 or block.block_type != BlockType.HEADING:
        return False
    text = _normalise(block.text).casefold().rstrip()
    greeting = text.rstrip(",，!！.。")
    return greeting in {"hi all", "hello all", "hello everyone", "dear all", "dear team"}


def _token_spans(text: str) -> list[re.Match[str]]:
    return list(re.finditer(r"[\u3400-\u9fff]|[A-Za-z0-9_]+|[^\s]", text))


def _truncate_tokens(text: str, limit: int) -> str:
    spans = _token_spans(text)
    if len(spans) <= limit:
        return text
    return text[:spans[limit - 1].end()].rstrip()


def _summary(text: str, short_tokens: int = 160, long_tokens: int = 180) -> tuple[str, str]:
    clean = _normalise(text)
    if len(_token_spans(clean)) <= short_tokens:
        return clean, "verbatim"
    sentences = [part.strip() for part in re.split(r"(?<=[。！？.!?])\s+", clean) if part.strip()]
    selected: list[str] = []
    used = 0
    for position in (0, len(sentences) - 1, *range(1, max(1, len(sentences) - 1))):
        if position < 0 or position >= len(sentences):
            continue
        sentence = sentences[position]
        if sentence in selected:
            continue
        sentence_tokens = len(_token_spans(sentence))
        if used + sentence_tokens > long_tokens and selected:
            continue
        selected.append(sentence)
        used += sentence_tokens
        if used >= long_tokens:
            break
    return _truncate_tokens(" ".join(selected), long_tokens), "extractive"


def _block_id(version_id: str, index: int, block: ContentBlock) -> str:
    existing = str(block.locator.get("block_id") or "")
    if existing:
        return existing
    seed = f"{version_id}:{index}:{block.block_type}:{block.level}:{block.text}"
    value = "blk_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]
    block.locator["block_id"] = value
    return value


def _looks_like_recovered_heading(block: ContentBlock) -> bool:
    text = _normalise(block.text)
    if block.block_type != BlockType.PARAGRAPH or not block.bold:
        return False
    if not text or len(text) > 100 or "\n" in block.text:
        return False
    if text[-1:] in {",", "，", ".", "。", ":", "：", ";", "；", "!", "！", "?", "？"}:
        return False
    field_labels = (
        "认证", "参数", "请求参数", "请求体", "返回值", "响应", "响应体",
        "负责人", "截止时间", "状态", "备注", "说明", "示例",
        "authentication", "parameters", "request", "response", "owner",
        "deadline", "status", "notes", "example",
    )
    label = text.casefold().strip("* _")
    if any(label == value or label.startswith(f"{value} ") for value in field_labels):
        return False
    return len(text.split()) <= 14


@dataclass
class _Node:
    id: str
    title: str
    level: int
    raw_level: int
    ordinal: int
    parent: "_Node | None"
    provenance: str
    own_indices: list[int] = field(default_factory=list)
    children: list["_Node"] = field(default_factory=list)

    @property
    def path(self) -> list[str]:
        chain: list[str] = []
        current: _Node | None = self
        while current:
            chain.append(current.title)
            current = current.parent
        return list(reversed(chain))


class NativeStructureProvider:
    """Build deterministic sections from parser-native block locations."""

    def build(self, document: Document) -> list[DocumentSection]:
        return _build_native_sections(document)


@dataclass(frozen=True)
class SectionHeadingSelection:
    indices: frozenset[int]
    recovered_indices: frozenset[int]
    duplicate_root: int | None


def select_section_heading_blocks(
    blocks: list[ContentBlock], document_title: str,
) -> SectionHeadingSelection:
    """Select the same native/recovered headings for chunking and SectionTree."""
    native_heading_count = sum(
        1 for index, block in enumerate(blocks)
        if block.block_type == BlockType.HEADING
        and block.text.strip()
        and not _is_non_navigable_heading(index, block)
        and not (
            block.level == 1
            and document_title
            and _title_key(block.text) == _title_key(document_title)
        )
    )
    # Recover bold-only headings only when the native hierarchy is sparse;
    # otherwise bold API fields can become false parent sections.
    recovered = (
        [index for index, block in enumerate(blocks) if _looks_like_recovered_heading(block)]
        if native_heading_count < 2 else []
    )
    recovered_set = frozenset(recovered if len(recovered) >= 2 else [])
    heading_indices = {
        index for index, block in enumerate(blocks)
        if block.block_type == BlockType.HEADING
        and block.text.strip()
        and not _is_non_navigable_heading(index, block)
    } | set(recovered_set)
    # A source H1 repeating the document title belongs to the root, not to a
    # second Section. The chunker still treats it as a text boundary.
    duplicate_root: int | None = None
    for index in sorted(heading_indices):
        block = blocks[index]
        if block.block_type == BlockType.HEADING:
            if (block.level == 1 and document_title
                    and _title_key(block.text) == _title_key(document_title)):
                duplicate_root = index
            break
    if duplicate_root is not None:
        heading_indices.remove(duplicate_root)
    return SectionHeadingSelection(
        indices=frozenset(heading_indices),
        recovered_indices=recovered_set,
        duplicate_root=duplicate_root,
    )


def _build_native_sections(document: Document) -> list[DocumentSection]:
    version_id = document.version_id or f"legacy:{document.doc_id}"
    blocks = document.content_blocks
    block_ids = [_block_id(version_id, index, block) for index, block in enumerate(blocks)]
    all_chunk_ids = [chunk.chunk_id for chunk in document.chunks]
    root = _Node(
        id=_id(version_id, [document.title]), title=document.title,
        level=0, raw_level=0, ordinal=0, parent=None, provenance="document",
    )

    selection = select_section_heading_blocks(blocks, document.title)
    recovered_set = set(selection.recovered_indices)
    heading_indices = set(selection.indices)
    duplicate_root = selection.duplicate_root

    stack: list[_Node] = []
    nodes: list[_Node] = [root]
    node_at_block: dict[int, _Node] = {}
    current = root
    ordinal = 0
    for index, block in enumerate(blocks):
        if index == duplicate_root:
            root.own_indices.append(index)
            continue
        if index not in heading_indices:
            current.own_indices.append(index)
            continue

        ordinal += 1
        raw_level = int(block.level or 1) if block.block_type == BlockType.HEADING else 1
        while stack and raw_level <= stack[-1].raw_level:
            stack.pop()
        parent = stack[-1] if stack else root
        level = parent.level + 1
        path = parent.path + [_normalise(block.text)]
        node = _Node(
            id=_id(version_id, path, ordinal),
            title=_normalise(block.text), level=level, raw_level=raw_level,
            ordinal=ordinal, parent=parent,
            provenance="native_heading" if block.block_type == BlockType.HEADING else "recovered_bold",
        )
        node.own_indices.append(index)
        parent.children.append(node)
        nodes.append(node)
        node_at_block[index] = node
        stack.append(node)
        current = node

    def subtree_indices(node: _Node) -> list[int]:
        values = list(node.own_indices)
        for child in node.children:
            values.extend(subtree_indices(child))
        return sorted(set(values))

    heading_chunk_starts = _heading_chunk_starts(document, [
        index for index in sorted(heading_indices) if index in node_at_block
    ])
    evidence_by_node: dict[str, list[str]] = {}
    ordered_heading_nodes = [node_at_block[index] for index in sorted(node_at_block)]
    for position, node in enumerate(ordered_heading_nodes):
        explicit = _evidence_for_node(document, node)
        if explicit:
            evidence_by_node[node.id] = explicit
            continue
        start = heading_chunk_starts[position] if position < len(heading_chunk_starts) else 0
        end = (
            heading_chunk_starts[position + 1]
            if position + 1 < len(heading_chunk_starts)
            else len(document.chunks)
        )
        if document.chunks:
            end = max(start + 1, end)
        evidence_by_node[node.id] = [chunk.chunk_id for chunk in document.chunks[start:end]]

    rows: list[DocumentSection] = []
    for node in nodes:
        own = sorted(set(node.own_indices))
        subtree = subtree_indices(node)
        own_text = "\n".join(blocks[index].to_markdown() for index in own)
        summary_indices = [
            index for index in subtree
            if blocks[index].block_type != BlockType.HEADING and index not in recovered_set
        ]
        summary_text = "\n".join(blocks[index].to_markdown() for index in summary_indices)
        summary, summary_type = _summary(summary_text or own_text or node.title)
        line_starts = [
            int(blocks[index].locator["line_start"])
            for index in subtree if blocks[index].locator.get("line_start") is not None
        ]
        line_ends = [
            int(blocks[index].locator["line_end"])
            for index in subtree if blocks[index].locator.get("line_end") is not None
        ]
        pages = [
            int(blocks[index].locator["page"])
            for index in subtree if blocks[index].locator.get("page") is not None
        ]
        raw = {
            "id": node.id,
            "version_id": version_id,
            "parent_id": node.parent.id if node.parent else None,
            "level": node.level,
            "title": node.title,
            "section_path": node.path,
            "page_start": min(pages) if pages else None,
            "page_end": max(pages) if pages else None,
            "summary": summary,
            "summary_type": summary_type,
            "evidence_ids": all_chunk_ids if node is root else evidence_by_node.get(node.id, []),
            "own_block_ids": [block_ids[index] for index in own],
            "subtree_block_ids": [block_ids[index] for index in subtree],
            "line_start": min(line_starts) if line_starts else None,
            "line_end": max(line_ends) if line_ends else None,
            "quality": "high" if len(nodes) > 1 else "low",
            "provenance": node.provenance,
            "ordinal": node.ordinal,
        }
        # Confluence ancestors are navigation context, not additional tree roots.
        ancestors = document.metadata.get("ancestor_path") or document.metadata.get("ancestors") or []
        aliases = document.metadata.get("aliases") or []
        normalized = normalize_section(
            raw,
            version_id=version_id,
            document_title=document.title,
            page_ancestor_path=ancestors if isinstance(ancestors, list) else [],
            aliases=aliases if isinstance(aliases, list) else [],
        )
        rows.append(DocumentSection(**normalized))
    return rows


def _heading_chunk_starts(document: Document, heading_indices: list[int]) -> list[int]:
    starts: list[int] = []
    cursor = 0
    for index in heading_indices:
        heading = document.content_blocks[index]
        found = next((
            position for position, chunk in enumerate(document.chunks[cursor:], cursor)
            if heading.text.casefold() in chunk.text.casefold()
        ), cursor)
        starts.append(found)
        cursor = min(found, len(document.chunks))
    return starts


def _evidence_for_node(document: Document, node: _Node) -> list[str]:
    expected = [_title_key(value) for value in node.path[1:]]
    matches: list[str] = []
    for chunk in document.chunks:
        path = [_title_key(value) for value in chunk.section_path]
        if path and path[0] == _title_key(document.title):
            path = path[1:]
        if path == expected:
            matches.append(chunk.chunk_id)
    return matches


def build_document_sections(
    document: Document,
    provider: DocumentStructureProvider | None = None,
) -> list[DocumentSection]:
    """Create deterministic, rebuildable navigation nodes from parsed structure."""
    return (provider or NativeStructureProvider()).build(document)
