import hashlib
import os
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


class BlockType(StrEnum):
    """内容块类型"""
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    LIST = "list"


class ContentBlock(BaseModel):
    """文档中的一个结构化内容块：段落、标题、表格、列表等"""
    block_type: BlockType
    level: int = 0                 # 标题层级 (1-6)，非标题为 0
    text: str = ""                 # 段落/标题/列表项的纯文本
    rows: list[list[str]] = Field(default_factory=list)    # 表格数据
    headers: list[str] = Field(default_factory=list)        # 表格列头
    bold: bool = False
    italic: bool = False

    @property
    def is_empty(self) -> bool:
        """判断该块是否无有效内容"""
        if self.block_type == BlockType.TABLE:
            return not self.rows and not self.headers
        return not self.text.strip()

    def to_markdown(self) -> str:
        """将内容块渲染为 Markdown 片段"""
        if self.block_type == BlockType.HEADING:
            level = max(1, min(6, self.level))
            return f"{'#' * level} {self.text}"
        elif self.block_type == BlockType.TABLE:
            return _table_to_markdown(self.rows, self.headers)
        elif self.block_type == BlockType.LIST:
            return f"- {self.text}"
        elif self.block_type == BlockType.PARAGRAPH:
            if self.bold:
                return f"**{self.text}**"
            return self.text
        return ""


def _table_to_markdown(rows: list[list[str]], headers: list[str]) -> str:
    """将表格行和可选的表头转为 GitHub 风格 Markdown 表格"""
    if not rows:
        return ""
    # 确保列数一致
    col_count = max(
        max((len(r) for r in rows), default=0),
        len(headers),
    )
    if col_count == 0:
        return ""
    # 补齐不足的列
    padded_rows = [r + [""] * (col_count - len(r)) for r in rows]
    if headers:
        padded_headers = list(headers) + [""] * (col_count - len(headers))
    else:
        padded_headers = [""] * col_count

    lines: list[str] = []
    lines.append("| " + " | ".join(str(c) for c in padded_headers) + " |")
    lines.append("| " + " | ".join(["---"] * col_count) + " |")
    for row in padded_rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


class Chunk(BaseModel):
    """单个文本分块"""
    index: int
    text: str
    chunk_id: str  # 全局唯一分块 ID，格式: "{doc_id}_chunk_{index}"


class Document(BaseModel):
    """解析后的文档模型，与 storage/document_store.py 的 JSON 格式对齐"""
    doc_id: str          # 文件 MD5 哈希，保证幂等
    title: str           # 文件名（不含扩展名）
    content: str         # 文档全文（已渲染为 Markdown 的字符串，兼容下游）
    space: str           # 来源文件夹名
    address: str         # 原始文件绝对路径
    last_updated: str    # ISO 格式时间戳
    chunks: list[Chunk] = Field(default_factory=list)
    source_url: str = ""
    content_blocks: list[ContentBlock] = Field(default_factory=list)  # 结构化内容块

    @staticmethod
    def generate_doc_id(file_path: str) -> str:
        """根据文件路径生成幂等 doc_id（MD5 哈希）"""
        return hashlib.md5(file_path.encode("utf-8")).hexdigest()

    @staticmethod
    def generate_last_updated(file_path: str) -> str:
        """读取文件修改时间，返回 ISO 格式字符串"""
        ts = os.path.getmtime(file_path)
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    @classmethod
    def from_file_path(
        cls,
        file_path: str,
        content: str,
        content_blocks: list[ContentBlock] | None = None,
    ) -> "Document":
        """从文件路径、已提取文本、可选结构化块构建 Document"""
        abs_path = os.path.abspath(file_path)
        title = os.path.splitext(os.path.basename(file_path))[0]
        space = os.path.basename(os.path.dirname(abs_path))
        return cls(
            doc_id=cls.generate_doc_id(abs_path),
            title=title,
            content=content,
            space=space,
            address=abs_path,
            last_updated=cls.generate_last_updated(abs_path),
            content_blocks=content_blocks or [],
        )
