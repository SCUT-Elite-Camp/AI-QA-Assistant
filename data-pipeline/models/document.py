import hashlib
import html
import os
from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class BlockType(StrEnum):
    """内容块类型"""
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    LIST = "list"


class BoundingBox(BaseModel):
    """Page-relative table or cell coordinates."""

    x0: float
    y0: float
    x1: float
    y1: float

    @model_validator(mode="after")
    def validate_extents(self) -> "BoundingBox":
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("bbox maximum coordinates must not precede minimum coordinates")
        return self


def _ordered_unique_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


class PageRegion(BaseModel):
    """One physical provenance region in a single page coordinate system."""

    page_number: int = Field(ge=1)
    bbox: BoundingBox
    block_ids: list[str] = Field(default_factory=list)
    table_ids: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def normalize_provenance(self) -> "PageRegion":
        self.block_ids = _ordered_unique_strings(self.block_ids)
        self.table_ids = _ordered_unique_strings(self.table_ids)
        self.sources = _ordered_unique_strings(self.sources)
        return self


class TableCell(BaseModel):
    row_index: int = Field(ge=0)
    column_index: int = Field(ge=0)
    text: str = ""
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    is_header: bool = False
    bbox: BoundingBox | None = None


class TableArtifact(BaseModel):
    """Canonical table representation, preserving parser provenance."""

    table_id: str
    cells: list[TableCell] = Field(default_factory=list)
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    header_row_count: int = Field(default=0, ge=0)
    caption: str = ""
    page_number: int | None = Field(default=None, ge=1)
    source_pages: list[int] = Field(default_factory=list)
    source_table_ids: list[str] = Field(default_factory=list)
    bbox: BoundingBox | None = None
    page_regions: list[PageRegion] = Field(default_factory=list)
    parser_name: str
    confidence: float = Field(ge=0.0, le=1.0)
    backend_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    quality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    quality_evidence: dict[str, float] = Field(default_factory=dict)
    acceptance: Literal["accepted", "review", "rejected"] = "review"
    image_path: str = ""
    warnings: list[str] = Field(default_factory=list)
    elapsed_ms: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def validate_shape(self) -> "TableArtifact":
        if self.header_row_count > self.row_count:
            raise ValueError("header_row_count cannot exceed row_count")
        for cell in self.cells:
            if cell.row_index + cell.row_span > self.row_count:
                raise ValueError("cell row span exceeds table bounds")
            if cell.column_index + cell.column_span > self.column_count:
                raise ValueError("cell column span exceeds table bounds")
        if not self.source_pages and self.page_number is not None:
            self.source_pages = [self.page_number]
        if not self.source_table_ids:
            self.source_table_ids = [self.table_id]
        if not self.page_regions and self.page_number is not None and self.bbox is not None:
            self.page_regions = [PageRegion(
                page_number=self.page_number,
                bbox=self.bbox,
                table_ids=list(self.source_table_ids),
                sources=["table"],
                confidence=self.confidence,
            )]
        if self.page_regions:
            self.page_regions = sorted(self.page_regions, key=lambda region: region.page_number)
            self.source_pages = sorted(set(
                [*self.source_pages, *(region.page_number for region in self.page_regions)]
            ))
        return self

    def to_matrix(self) -> list[list[str]]:
        matrix = [["" for _ in range(self.column_count)] for _ in range(self.row_count)]
        for cell in self.cells:
            for row_index in range(cell.row_index, cell.row_index + cell.row_span):
                for column_index in range(cell.column_index, cell.column_index + cell.column_span):
                    matrix[row_index][column_index] = cell.text
        return matrix

    def header_rows(self) -> list[list[str]]:
        return self.to_matrix()[: self.header_row_count]

    def body_rows(self) -> list[list[str]]:
        return self.to_matrix()[self.header_row_count :]

    def legacy_headers(self) -> list[str]:
        return [" / ".join(part for part in column if part) for column in zip(*self.header_rows())] if self.header_row_count else []

    def to_markdown(self) -> str:
        return _table_to_markdown(self.body_rows(), self.legacy_headers())

    def to_html(self) -> str:
        lines = [f'<table data-table-id="{html.escape(self.table_id, quote=True)}">']
        if self.caption:
            lines.append(f"  <caption>{html.escape(self.caption)}</caption>")
        for row_index in range(self.row_count):
            lines.append("  <tr>")
            for cell in sorted((item for item in self.cells if item.row_index == row_index), key=lambda item: item.column_index):
                tag = "th" if cell.is_header or row_index < self.header_row_count else "td"
                spans = (f' rowspan="{cell.row_span}"' if cell.row_span > 1 else "") + (f' colspan="{cell.column_span}"' if cell.column_span > 1 else "")
                lines.append(f"    <{tag}{spans}>{html.escape(cell.text).replace(chr(10), '<br>')}</{tag}>")
            lines.append("  </tr>")
        lines.append("</table>")
        return "\n".join(lines)

    def to_row_chunks(self) -> list[str]:
        headers = self.legacy_headers()
        return [" | ".join(f"{headers[index]}: {value.strip()}" if index < len(headers) and headers[index] else value.strip() for index, value in enumerate(row) if value.strip()) for row in self.body_rows()]


class ContentBlock(BaseModel):
    """文档中的一个结构化内容块：段落、标题、表格、列表等"""
    block_type: BlockType
    level: int = 0                 # 标题层级 (1-6)，非标题为 0
    text: str = ""                 # 段落/标题/列表项的纯文本
    block_id: str = ""
    page_number: int | None = Field(default=None, ge=1)
    bbox: BoundingBox | None = None
    font_name: str = ""
    font_size: float = Field(default=0.0, ge=0.0)
    rotation: float = 0.0
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: Literal["native", "ocr", "table"] = "native"
    extraction_method: str = ""
    rows: list[list[str]] = Field(default_factory=list)    # 表格数据
    headers: list[str] = Field(default_factory=list)        # 表格列头
    table: TableArtifact | None = None
    bold: bool = False
    italic: bool = False
    locator: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def derive_legacy_table_fields(self) -> "ContentBlock":
        if self.block_type == BlockType.TABLE and self.table is not None:
            if not self.headers:
                self.headers = self.table.legacy_headers()
            if not self.rows:
                self.rows = self.table.body_rows()
        return self

    @property
    def is_empty(self) -> bool:
        """判断该块是否无有效内容"""
        if self.block_type == BlockType.TABLE:
            return self.table is None and not self.rows and not self.headers
        return not self.text.strip()

    @property
    def is_indexable(self) -> bool:
        """Whether this block belongs in the primary index/rendered content."""
        return not (
            self.block_type == BlockType.TABLE
            and self.table is not None
            and self.table.acceptance != "accepted"
        )

    def to_markdown(self) -> str:
        """将内容块渲染为 Markdown 片段"""
        if self.block_type == BlockType.HEADING:
            level = max(1, min(6, self.level))
            return f"{'#' * level} {self.text}"
        elif self.block_type == BlockType.TABLE:
            return self.table.to_markdown() if self.table is not None else _table_to_markdown(self.rows, self.headers)
        elif self.block_type == BlockType.LIST:
            return f"- {self.text}"
        elif self.block_type == BlockType.PARAGRAPH:
            if self.bold:
                return f"**{self.text}**"
            return self.text
        return ""

    def to_index_markdown(self) -> str:
        """Render this block for indexing, omitting review-only tables."""
        return self.to_markdown() if self.is_indexable else ""


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
    section_path: list[str] = Field(default_factory=list)
    block_start: int | None = None
    block_end: int | None = None
    overlap_prefix_length: int = 0  # duplicated retrieval context, not source content
    chunk_type: str = "text"
    table_id: str = ""
    block_id: str = ""
    page_number: int | None = Field(default=None, ge=1)
    bbox: BoundingBox | None = None
    source: Literal["native", "ocr", "table"] = "native"
    source_pages: list[int] = Field(default_factory=list)
    page_regions: list[PageRegion] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_page_regions(self) -> "Chunk":
        if not self.page_regions and self.page_number is not None and self.bbox is not None:
            raw_sources = self.metadata.get("sources", [])
            if isinstance(raw_sources, str):
                raw_sources = [raw_sources]
            if not isinstance(raw_sources, list):
                raw_sources = []
            raw_block_ids = self.metadata.get("block_ids", [])
            if isinstance(raw_block_ids, str):
                raw_block_ids = [raw_block_ids]
            if not isinstance(raw_block_ids, list):
                raw_block_ids = []
            raw_confidence = self.metadata.get("confidence", 1.0)
            try:
                confidence = float(raw_confidence)
            except (TypeError, ValueError):
                confidence = 1.0
            if not 0.0 <= confidence <= 1.0:
                confidence = 1.0
            self.page_regions = [PageRegion(
                page_number=self.page_number,
                bbox=self.bbox,
                block_ids=[self.block_id, *raw_block_ids],
                table_ids=[self.table_id],
                sources=[self.source, *raw_sources],
                confidence=confidence,
            )]
        if self.page_regions:
            self.page_regions = sorted(self.page_regions, key=lambda region: region.page_number)
            self.source_pages = sorted(set(
                [*self.source_pages, *(region.page_number for region in self.page_regions)]
            ))
            if len(self.source_pages) == 1 and len(self.page_regions) == 1:
                self.page_number = self.source_pages[0]
                self.bbox = self.page_regions[0].bbox
            elif len(self.page_regions) > 1 or len(self.source_pages) > 1:
                self.page_number = None
                self.bbox = None
        return self


class DocumentSection(BaseModel):
    """Version-derived navigation node; Evidence chunks remain authoritative."""

    id: str
    version_id: str
    parent_id: str | None = None
    level: int = 0
    title: str
    section_path: list[str] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    summary: str = ""
    extractive_summary: str = ""
    llm_summary: str = ""
    summary_type: str = ""
    summary_model: str = ""
    summary_prompt_version: str = ""
    summary_input_hash: str = ""
    summary_status: str = "not_requested"
    evidence_ids: list[str] = Field(default_factory=list)
    own_block_ids: list[str] = Field(default_factory=list)
    subtree_block_ids: list[str] = Field(default_factory=list)
    line_start: int | None = None
    line_end: int | None = None
    quality: str = "low"
    provenance: str = "native"
    ordinal: int = 0
    navigation_text: str = ""


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
    metadata: dict = Field(default_factory=dict)                      # 侧车溯源元数据（如 Confluence）
    doc_type: str = ""
    version_id: str = ""
    active_version: bool = True
    sections: list[DocumentSection] = Field(default_factory=list)

    def render_index_content(self) -> str:
        """Render the compatibility/index view from indexable content blocks.

        Documents created by older parsers may not have structured blocks; in
        that case their already-rendered ``content`` remains the fallback.
        """
        if not self.content_blocks:
            return self.content
        return "\n\n".join(
            rendered
            for block in self.content_blocks
            if not block.is_empty
            for rendered in (block.to_index_markdown(),)
            if rendered
        )

    @staticmethod
    def generate_doc_id(file_path: str) -> str:
        """根据文件路径生成幂等 doc_id（MD5 哈希）"""
        return hashlib.md5(file_path.encode("utf-8")).hexdigest()

    @staticmethod
    def generate_last_updated(file_path: str) -> str:
        """读取文件修改时间，返回 ISO 格式字符串"""
        ts = os.path.getmtime(file_path)
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    @staticmethod
    def generate_version_id(file_path: str) -> str:
        digest = hashlib.sha256()
        with open(file_path, "rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return f"ver_{digest.hexdigest()}"

    @classmethod
    def from_file_path(
        cls,
        file_path: str,
        content: str,
        content_blocks: list[ContentBlock] | None = None,
    ) -> "Document":
        """从文件路径、已提取文本、可选结构化块构建 Document

        若存在同名侧车文件 ``<file>.meta.json``（如 Confluence 连接器写入），
        则读取其中的 source_url / title / last_updated / metadata 以补全溯源信息。
        """
        import json

        abs_path = os.path.abspath(file_path)
        title = os.path.splitext(os.path.basename(file_path))[0]
        space = os.path.basename(os.path.dirname(abs_path))
        last_updated = cls.generate_last_updated(abs_path)
        source_url = ""
        metadata: dict = {}
        doc_type = cls.infer_doc_type(abs_path, metadata)

        meta_path = abs_path + ".meta.json"
        if os.path.exists(meta_path):
            try:
                with open(meta_path, encoding="utf-8") as _mf:
                    _meta = json.load(_mf)
                source_url = _meta.get("source_url", "") or source_url
                title = _meta.get("title", title) or title
                last_updated = _meta.get("last_updated", last_updated) or last_updated
                metadata = _meta
                doc_type = cls.infer_doc_type(abs_path, metadata)
            except Exception as _e:  # noqa: BLE001
                print(f"  ⚠ 读取侧车元数据失败: {meta_path}，错误: {_e}")

        return cls(
            doc_id=cls.generate_doc_id(abs_path),
            title=title,
            content=content,
            space=space,
            address=abs_path,
            last_updated=last_updated,
            source_url=source_url,
            content_blocks=content_blocks or [],
            metadata=metadata,
            doc_type=doc_type,
            version_id=cls.generate_version_id(abs_path),
        )

    @staticmethod
    def infer_doc_type(address: str, metadata: dict | None = None) -> str:
        """Resolve a stable document type from metadata or the source filename."""
        metadata = metadata or {}
        value = metadata.get("doc_type") or metadata.get("content_type")
        candidate = str(value or "").strip().lower()
        if "/" in candidate:
            candidate = candidate.rsplit("/", 1)[-1]
        if candidate in {"attachment", "page", "hybrid"}:
            candidate = ""
        if not candidate:
            filename = str(metadata.get("filename") or address)
            candidate = os.path.splitext(filename)[1]
        return candidate.removeprefix(".").lower()[:64]
