"""
文本切片模块。

提供两种切片策略:
- chunk_text():          字符级滑动窗口（向后兼容，用于无结构信息的纯文本）
- chunk_from_blocks():   块感知切片（保证不切割表格和标题边界）
"""

import re

from models.document import BlockType, Chunk, ContentBlock

from .structure import select_section_heading_blocks


_SENTENCE_END = re.compile(r"(?<=[.!?。！？；;])(?=\s|[^\w])|(?<=[。！？；])")


def split_prose_at_boundaries(text: str, max_chars: int) -> list[str]:
    """Split oversized prose at complete sentences or whitespace, preserving every character.

    A single unbreakable token may exceed the target; corrupting a word is worse
    than an oversized Evidence. The returned parts concatenate to the source.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if len(text) <= max_chars:
        return [text] if text else []
    parts: list[str] = []
    start = 0
    while start < len(text):
        if len(text) - start <= max_chars:
            parts.append(text[start:])
            break
        limit = start + max_chars
        candidates = [match.end() for match in _SENTENCE_END.finditer(text, start, limit)]
        boundary = candidates[-1] if candidates else -1
        if boundary <= start:
            boundary = max(text.rfind(" ", start + 1, limit + 1), text.rfind("\n", start + 1, limit + 1))
            if boundary > start:
                boundary += 1
        if boundary <= start:
            next_space = re.search(r"\s", text[limit:])
            boundary = limit + next_space.end() if next_space else len(text)
        parts.append(text[start:boundary])
        start = boundary
    return parts

def chunk_text(
    text: str,
    doc_id: str,
    chunk_size: int = 500,
    overlap: int = 100,
) -> list[Chunk]:
    """
    将文本按字符数切分为重叠分块（字符级滑动窗口）。

    Args:
        text: 待切分的全文（纯文本或 Markdown）
        doc_id: 所属文档 ID
        chunk_size: 每个分块的目标字符数
        overlap: 相邻分块之间的重叠字符数

    Returns:
        Chunk 列表，chunk_id 格式为 "{doc_id}_chunk_{index}"
    """
    if not text:
        return []

    chunks: list[Chunk] = []
    step = chunk_size - overlap
    if step <= 0:
        raise ValueError(f"chunk_size ({chunk_size}) 必须大于 overlap ({overlap})")

    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunk_text_content = text[start:end]
        chunk = Chunk(
            index=len(chunks),
            text=chunk_text_content,
            chunk_id=f"{doc_id}_chunk_{len(chunks)}",
        )
        chunks.append(chunk)
        if end >= text_len:
            break
        start += step

    return chunks

def chunk_from_blocks(
    blocks: list[ContentBlock],
    doc_id: str,
    chunk_size: int = 500,
    overlap: int = 100,
    *,
    document_title: str = "",
) -> list[Chunk]:
    """
    块感知切片：逐块累积 Markdown 文本，保证不切割表格和标题边界。

    策略:
    - 逐块累积渲染后的 Markdown 文本
    - 当添加下一块将超过 chunk_size 时，flush 当前缓冲为一个 chunk
    - 单个大表格如果超过 chunk_size，独立成一个 chunk（不切割）
    - 原生标题及结构层恢复的加粗章节标题均为硬边界
    - overlap 仅限同一章节，不跨章节复制文本

    Args:
        blocks: 结构化内容块列表（来自解析器）
        doc_id: 所属文档 ID
        chunk_size: 每个分块的目标字符数
        overlap: 相邻分块之间的重叠字符数
        document_title: 文档标题，用于与 SectionTree 共用相同的章节识别

    Returns:
        Chunk 列表
    """
    if not blocks:
        return []

    selection = select_section_heading_blocks(blocks, document_title)
    boundary_indices = set(selection.indices) | {
        index for index, block in enumerate(blocks)
        if block.block_type == BlockType.HEADING and block.text.strip()
    }

    # Keep original block positions so Evidence can be mapped to a Section
    # without searching for a heading string inside arbitrary chunk text.
    rendered_blocks: list[tuple[int, ContentBlock, str]] = []
    for block_index, cb in enumerate(blocks):
        md = cb.to_markdown()
        if md:
            rendered_blocks.append((block_index, cb, md))

    if not rendered_blocks:
        return []

    chunks: list[Chunk] = []
    buffer: list[str] = []    # 当前累积的块文本列表
    buffer_indices: list[int] = []
    buffer_len = 0            # 当前缓冲区的总字符数
    heading_stack: list[tuple[int, str]] = []
    current_section_path: list[str] = []

    def _heading_only_buffer() -> bool:
        return len(buffer) == 1 and buffer_indices[0] in boundary_indices

    def _flush(prefix: str = "") -> str:
        """将当前缓冲 flush 为一个 chunk，返回尾部 overlap 文本"""
        nonlocal buffer, buffer_indices, buffer_len
        if not buffer:
            return prefix or ""
        if _heading_only_buffer():
            # A section title is navigation metadata, not standalone factual
            # Evidence. Keep it for the next body block or omit empty sections.
            buffer, buffer_indices, buffer_len = [], [], 0
            return ""
        body = "\n\n".join(buffer)
        full_text = (prefix + "\n\n" + body) if prefix else body
        chunk = Chunk(
            index=len(chunks),
            text=full_text,
            chunk_id=f"{doc_id}_chunk_{len(chunks)}",
            section_path=list(current_section_path),
            block_start=min(buffer_indices) if buffer_indices else None,
            block_end=max(buffer_indices) if buffer_indices else None,
            overlap_prefix_length=len(prefix) + 2 if prefix else 0,
        )
        chunks.append(chunk)
        # 计算重叠尾部
        tail = full_text[-overlap:] if len(full_text) > overlap else full_text
        buffer = []
        buffer_indices = []
        buffer_len = 0
        return tail

    overlap_prefix = ""

    for block_index, content_block, bt in rendered_blocks:
        if block_index in boundary_indices:
            # A heading starts a new semantic section. Never carry body text or
            # overlap from its previous sibling into the new Evidence chunk.
            _flush(overlap_prefix)
            overlap_prefix = ""
            level = (
                max(1, min(6, int(content_block.level or 1)))
                if content_block.block_type == BlockType.HEADING else 1
            )
            heading_stack = [entry for entry in heading_stack if entry[0] < level]
            heading_stack.append((level, content_block.text.strip()))
            current_section_path = [title for _, title in heading_stack]

        bt_len = len(bt)
        sep_len = 2 if buffer else 0  # "\n\n" 分隔符

        # 情况 1：单个块超过 chunk_size（整张超大表格）
        if bt_len > chunk_size:
            heading_prefix = buffer[0] if _heading_only_buffer() else ""
            heading_start = buffer_indices[0] if heading_prefix else block_index
            if heading_prefix:
                buffer, buffer_indices, buffer_len = [], [], 0
            else:
                overlap_prefix = _flush(overlap_prefix)
            if (content_block.block_type in {BlockType.TABLE, BlockType.LIST}
                    or content_block.locator.get("code")):
                # Tables, individual list items and code are source objects.
                # Keep each intact even if it exceeds the retrieval target.
                chunks.append(Chunk(
                    index=len(chunks),
                    text=f"{heading_prefix}\n\n{bt}" if heading_prefix else bt,
                    chunk_id=f"{doc_id}_chunk_{len(chunks)}",
                    section_path=list(current_section_path),
                    block_start=heading_start,
                    block_end=block_index,
                ))
                overlap_prefix = bt[-overlap:] if len(bt) > overlap else bt
            else:
                # Long prose stays inside its Section and never cuts a word or sentence
                # merely to satisfy the target size. No duplicate overlap is generated.
                for part_index, part in enumerate(split_prose_at_boundaries(bt, chunk_size)):
                    chunks.append(Chunk(
                        index=len(chunks),
                        text=(f"{heading_prefix}\n\n{part}"
                              if heading_prefix and part_index == 0 else part),
                        chunk_id=f"{doc_id}_chunk_{len(chunks)}",
                        section_path=list(current_section_path),
                        block_start=heading_start if heading_prefix and part_index == 0 else block_index,
                        block_end=block_index,
                    ))
                overlap_prefix = ""
            continue

        # 情况 2：加入当前块后可能超过限制 → flush
        if buffer_len + sep_len + bt_len > chunk_size and buffer and not _heading_only_buffer():
            overlap_prefix = _flush(overlap_prefix)
            sep_len = 0  # buffer 已清空

        # 情况 3：正常累积
        if buffer:
            buffer.append(bt)
            buffer_indices.append(block_index)
            buffer_len += 2 + bt_len
        else:
            buffer.append(bt)
            buffer_indices.append(block_index)
            buffer_len = bt_len

    # flush 剩余
    _flush(overlap_prefix)

    return chunks
