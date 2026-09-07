from __future__ import annotations

import re
from pathlib import Path

from models.document import BlockType, ContentBlock, Document
from parsers.base import BaseParser


class MarkdownParser(BaseParser):
    """Parse Markdown headings and body blocks without external state."""

    _heading = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

    def parse(self, file_path: str) -> Document:
        data = Path(file_path).read_bytes()
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("gb18030")
        blocks: list[ContentBlock] = []
        offset = 0
        paragraph: list[str] = []
        paragraph_start = 0

        def flush() -> None:
            nonlocal paragraph
            content = "\n".join(paragraph).strip()
            if content:
                blocks.append(ContentBlock(
                    block_type=BlockType.PARAGRAPH,
                    text=content,
                    locator={"char_start": paragraph_start, "char_end": offset},
                ))
            paragraph = []

        for line in text.splitlines(keepends=True):
            stripped = line.rstrip("\r\n")
            match = self._heading.match(stripped)
            if match:
                flush()
                blocks.append(ContentBlock(
                    block_type=BlockType.HEADING,
                    level=len(match.group(1)),
                    text=match.group(2).strip(),
                    locator={"char_start": offset, "char_end": offset + len(line)},
                ))
            else:
                if not paragraph:
                    paragraph_start = offset
                paragraph.append(stripped)
            offset += len(line)
        flush()
        content = "\n\n".join(block.to_markdown() for block in blocks if not block.is_empty)
        return Document.from_file_path(file_path, content, content_blocks=blocks)

    @staticmethod
    def supported_extensions() -> list[str]:
        return [".md", ".markdown"]
