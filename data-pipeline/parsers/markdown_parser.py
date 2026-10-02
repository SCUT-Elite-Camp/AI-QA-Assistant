from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt

from models.document import BlockType, ContentBlock, Document
from parsers.base import BaseParser
from shared_runtime.document_sections import stable_document_version_id


class MarkdownParser(BaseParser):
    """Parse Markdown through a block AST and retain source locations."""

    def __init__(self) -> None:
        self._parser = MarkdownIt("commonmark", {"html": True}).enable("table")

    def parse(self, file_path: str) -> Document:
        path = Path(file_path)
        data = path.read_bytes()
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("gb18030")
        metadata = self._load_metadata(path)
        document = self.parse_text(text, source=str(path.resolve()), metadata=metadata)
        if not metadata:
            document.space = path.parent.name
            document.last_updated = Document.generate_last_updated(str(path))
            document.doc_type = path.suffix.removeprefix(".").lower()
        return document

    def parse_text(
        self,
        text: str,
        *,
        source: str,
        metadata: dict[str, Any] | None = None,
    ) -> Document:
        """Parse in-memory Markdown without requiring a temporary file."""
        meta = dict(metadata or {})
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        page_id = str(meta.get("page_id") or "")
        space_id = str(meta.get("space_id") or meta.get("space_key") or "")
        page_version = str(meta.get("version") or "")
        doc_key = f"confluence:{space_id}:{page_id}" if page_id else source
        title = str(meta.get("title") or Path(source).stem)
        version_id = (
            stable_document_version_id(
                source_scope="enterprise",
                knowledge_base_id=space_id or "confluence",
                document_id=page_id,
                version=page_version or "0",
                content_sha256=content_hash,
            )
            if page_id
            else "ver_" + hashlib.sha256(content_hash.encode("utf-8")).hexdigest()
        )
        blocks = self._parse_blocks(text, doc_key)
        return Document(
            doc_id=hashlib.md5(doc_key.encode("utf-8")).hexdigest(),
            title=title,
            content=text.strip(),
            space=str(meta.get("space_key") or Path(source).parent.name),
            address=source,
            last_updated=str(meta.get("last_updated") or ""),
            source_url=str(meta.get("source_url") or ""),
            content_blocks=blocks,
            metadata=meta,
            doc_type="md",
            version_id=version_id,
        )

    def _parse_blocks(self, text: str, document_key: str) -> list[ContentBlock]:
        tokens = self._parser.parse(text)
        lines = text.splitlines(keepends=True)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))
        local_ids = self._local_id_comments(lines)

        blocks: list[ContentBlock] = []
        list_depth = 0
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token.type in {"bullet_list_open", "ordered_list_open"}:
                list_depth += 1
                index += 1
                continue
            if token.type in {"bullet_list_close", "ordered_list_close"}:
                list_depth = max(0, list_depth - 1)
                index += 1
                continue
            if token.type == "heading_open" and token.map:
                inline = tokens[index + 1] if index + 1 < len(tokens) else None
                content = self._plain_inline(inline)
                if content:
                    blocks.append(self._block(
                        BlockType.HEADING, content, token.map, offsets, document_key,
                        level=int(token.tag[1:]), local_ids=local_ids,
                    ))
            elif token.type == "paragraph_open" and token.map and list_depth == 0:
                inline = tokens[index + 1] if index + 1 < len(tokens) else None
                content = self._plain_inline(inline)
                if content:
                    blocks.append(self._block(
                        BlockType.PARAGRAPH, content, token.map, offsets, document_key,
                        bold=self._is_all_strong(inline), local_ids=local_ids,
                    ))
            elif token.type == "list_item_open" and token.map:
                content = self._list_item_text(tokens, index)
                if content:
                    block = self._block(
                        BlockType.LIST, content, token.map, offsets, document_key,
                        local_ids=local_ids,
                    )
                    block.locator["list_depth"] = list_depth
                    block.locator["ordered"] = self._is_ordered_list(tokens, index)
                    blocks.append(block)
            elif token.type in {"fence", "code_block"} and token.map:
                block = self._block(
                    BlockType.PARAGRAPH, token.content.rstrip("\n"), token.map,
                    offsets, document_key, local_ids=local_ids,
                )
                block.locator.update({"code": True, "language": token.info.strip()})
                blocks.append(block)
            elif token.type == "table_open" and token.map:
                raw = "".join(lines[token.map[0]:token.map[1]]).strip()
                headers, rows = self._parse_table(raw)
                block = self._block(
                    BlockType.TABLE, raw, token.map, offsets, document_key,
                    local_ids=local_ids,
                )
                block.headers = headers
                block.rows = rows
                blocks.append(block)
            index += 1

        return sorted(blocks, key=lambda item: (
            int(item.locator.get("line_start", 0)),
            0 if item.block_type == BlockType.HEADING else 1,
        ))

    @staticmethod
    def _block(
        block_type: BlockType,
        text: str,
        line_map: list[int],
        offsets: list[int],
        document_key: str,
        *,
        level: int = 0,
        bold: bool = False,
        local_ids: dict[int, str],
    ) -> ContentBlock:
        start, end = line_map
        local_id = local_ids.get(start)
        stable_locator = f"local-id:{local_id}" if local_id else f"lines:{start}:{end}:{text}"
        seed = f"{document_key}:{block_type}:{stable_locator}"
        locator: dict[str, Any] = {
            "block_id": "blk_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20],
            "line_start": start + 1,
            "line_end": max(start + 1, end),
            "char_start": offsets[min(start, len(offsets) - 1)],
            "char_end": offsets[min(end, len(offsets) - 1)],
        }
        if local_id:
            locator["confluence_local_id"] = local_id
        return ContentBlock(
            block_type=block_type,
            level=level,
            text=text,
            bold=bold,
            locator=locator,
        )

    @staticmethod
    def _local_id_comments(lines: list[str]) -> dict[int, str]:
        prefix = "<!-- confluence-local-id:"
        found: dict[int, str] = {}
        pending: str | None = None
        for number, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(prefix) and stripped.endswith("-->"):
                pending = stripped[len(prefix):-3].strip()
            elif pending and stripped:
                found[number] = pending
                pending = None
        return found

    @staticmethod
    def _is_all_strong(inline: Any) -> bool:
        children = [
            item for item in list(getattr(inline, "children", None) or [])
            if item.type not in {"softbreak", "hardbreak"}
            and not (item.type == "text" and not item.content)
        ]
        return (
            len(children) >= 3
            and children[0].type == "strong_open"
            and children[-1].type == "strong_close"
            and any(item.type in {"text", "code_inline"} for item in children[1:-1])
        )

    @staticmethod
    def _plain_inline(inline: Any) -> str:
        if not inline or inline.type != "inline":
            return ""
        children = list(getattr(inline, "children", None) or [])
        if not children:
            return inline.content.strip()
        parts: list[str] = []
        for item in children:
            if item.type in {"text", "code_inline", "html_inline"}:
                parts.append(item.content)
            elif item.type in {"softbreak", "hardbreak"}:
                parts.append("\n")
            elif item.type == "image":
                parts.append(item.content or item.attrGet("alt") or "image")
        return "".join(parts).strip()

    @staticmethod
    def _list_item_text(tokens: list[Any], start: int) -> str:
        level = tokens[start].level
        texts: list[str] = []
        for token in tokens[start + 1:]:
            if token.type == "list_item_close" and token.level == level:
                break
            if token.type == "inline" and token.content.strip():
                texts.append(MarkdownParser._plain_inline(token))
        return " ".join(texts)

    @staticmethod
    def _is_ordered_list(tokens: list[Any], start: int) -> bool:
        for token in reversed(tokens[:start]):
            if token.type == "ordered_list_open":
                return True
            if token.type == "bullet_list_open":
                return False
        return False

    @staticmethod
    def _parse_table(raw: str) -> tuple[list[str], list[list[str]]]:
        parsed: list[list[str]] = []
        for line in raw.splitlines():
            parsed.append([
                cell.strip().replace("\\|", "|")
                for cell in line.strip().strip("|").split("|")
            ])
        if len(parsed) < 2:
            return [], parsed
        return parsed[0], parsed[2:]

    @staticmethod
    def _load_metadata(path: Path) -> dict[str, Any]:
        for candidate in (path.with_name("page.meta.json"), Path(str(path) + ".meta.json")):
            if candidate.exists():
                try:
                    value = json.loads(candidate.read_text(encoding="utf-8"))
                    if isinstance(value, dict):
                        return value
                except (OSError, json.JSONDecodeError):
                    continue
        return {}

    @staticmethod
    def supported_extensions() -> list[str]:
        return [".md", ".markdown"]
