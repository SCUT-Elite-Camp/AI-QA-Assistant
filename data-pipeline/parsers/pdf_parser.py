"""
PDF 解析器：使用 PyMuPDF 提取文本、表格和结构信息。

特性:
- 表格提取：page.find_tables() → Markdown 表格
- 页眉页脚去除：按 y 坐标过滤（上下各 15%）
- 标题检测：基于字体大小和加粗的启发式推断（PDF 无语义标题信息）
- 结构保留：输出 ContentBlock 列表 + 渲染 Markdown
"""

import re

import pymupdf as fitz
from models.document import Document, ContentBlock, BlockType, TableArtifact
from parsers.base import BaseParser
from parsers.table_backends import (
    CamelotTableBackend,
    GMFTTableBackend,
    PaddleOCRTableBackend,
    PyMuPDFTableBackend,
)
from parsers.table_router import TableRouter

# ── 配置常量 ──
HEADER_FOOTER_RATIO = 0.15       # 页面上/下边缘区域比例
HEADING_FONT_RATIO = 1.15        # 字号超过正文中位数此倍数视为候选标题
HEADING_MIN_LEVEL_1_RATIO = 1.5  # 一级标题的最低字号比例
HEADING_MIN_LEVEL_2_RATIO = 1.3  # 二级标题的最低字号比例

class PDFParser(BaseParser):
    """使用 PyMuPDF 解析 PDF 文件，提取表格、结构信息并去除页眉页脚"""

    def __init__(self, router: TableRouter | None = None):
        self.table_router = router or TableRouter(
            PyMuPDFTableBackend(),
            CamelotTableBackend(),
            PaddleOCRTableBackend(),
            complex_fallback=GMFTTableBackend(),
        )

    def parse(self, file_path: str) -> Document:
        pdf_doc = fitz.open(file_path)
        all_blocks: list[ContentBlock] = []
        body_font_sizes: list[float] = []
        page_heights: dict[int, float] = {}

        # ── 第一轮：逐页提取内容块和正文字号 ──
        for page_index, page in enumerate(pdf_doc, start=1):
            page_height = page.rect.height
            page_heights[page_index] = float(page_height)
            header_y = page_height * HEADER_FOOTER_RATIO
            footer_y = page_height * (1 - HEADER_FOOTER_RATIO)

            # 1. 先提取并验证候选；只有已接受表格才允许排除重叠正文。
            text_coverage = self._text_coverage(page)
            artifacts = self.table_router.route_page(
                page,
                page_number=page_index,
                text_coverage=text_coverage,
                file_path=file_path,
            )
            table_regions = [
                (artifact.bbox.x0, artifact.bbox.y0, artifact.bbox.x1, artifact.bbox.y1)
                for artifact in artifacts
                if artifact.bbox is not None and artifact.acceptance == "accepted"
            ]

            # 2. 提取结构化文本块
            text_dict = page.get_text("dict")
            blocks = text_dict.get("blocks", [])

            # 用 (y_position, ContentBlock) 收集，便于按阅读顺序排序
            positioned: list[tuple[float, ContentBlock]] = []

            for block in blocks:
                if block["type"] != 0:  # 只处理文本块
                    continue
                bbox = block["bbox"]
                y_mid = (bbox[1] + bbox[3]) / 2

                # 跳过页眉/页脚区域
                if y_mid < header_y or y_mid > footer_y:
                    continue

                # 跳过与表格重叠的文本块
                if self._overlaps_any_table(bbox, table_regions):
                    continue

                cb = self._block_to_content_block(block)
                if cb:
                    positioned.append((y_mid, cb))
                    # 收集字号用于后续标题判定
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            size = span.get("size", 0)
                            if size > 0:
                                body_font_sizes.append(size)

            # 3. 插入已经过评分和路由选择的统一表格对象。
            for artifact in artifacts:
                cb = ContentBlock(block_type=BlockType.TABLE, table=artifact)
                table_y = artifact.bbox.y0 if artifact.bbox is not None else 0.0
                positioned.append((table_y, cb))

            # 4. 按垂直位置排序，保持阅读顺序
            positioned.sort(key=lambda item: item[0])
            all_blocks.extend(cb for _, cb in positioned)

        pdf_doc.close()

        # Merge only strict, high-signal continuations: adjacent pages, same
        # columns/headers, previous table at page bottom and next at page top.
        all_blocks = self._stitch_table_blocks(all_blocks, page_heights)

        # ── 第二轮：基于字号统计判定标题 ──
        if body_font_sizes:
            median_size = sorted(body_font_sizes)[len(body_font_sizes) // 2]
        else:
            median_size = 11.0

        for cb in all_blocks:
            if cb.block_type in (BlockType.PARAGRAPH,):
                self._promote_to_heading(cb, median_size)

        # ── 渲染为 Markdown 内容 ──
        content = "\n\n".join(
            cb.to_markdown() for cb in all_blocks if not cb.is_empty
        )
        content = self._clean_text(content)

        return Document.from_file_path(file_path, content, content_blocks=all_blocks)

    # ── 区域与重叠判断 ──

    @staticmethod
    def _extract_table_regions(tables) -> list[tuple[float, float, float, float]]:
        """获取页面上所有表格的边界框"""
        regions: list[tuple[float, float, float, float]] = []
        for t in tables:
            try:
                regions.append(tuple(t.bbox))
            except Exception:
                pass
        return regions

    @staticmethod
    def _overlaps_any_table(bbox: tuple, regions: list[tuple[float, float, float, float]]) -> bool:
        """判断一个矩形是否与任一表格区域重叠"""
        if not regions:
            return False
        ax0, ay0, ax1, ay1 = bbox
        for (tx0, ty0, tx1, ty1) in regions:
            if not (ax1 <= tx0 or ax0 >= tx1 or ay1 <= ty0 or ay0 >= ty1):
                return True
        return False

    # ── 文本块转换 ──

    @staticmethod
    def _block_to_content_block(block: dict) -> ContentBlock | None:
        """将 PyMuPDF 文本 dict 块转为 ContentBlock，同时提取格式信息"""
        text_parts: list[str] = []
        max_font_size = 0.0
        has_bold = False
        has_italic = False
        font_name = ""

        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text_parts.append(span.get("text", ""))
                size = span.get("size", 0)
                if size > max_font_size:
                    max_font_size = size
                flags = span.get("flags", 0)
                if flags & fitz.TEXT_FONT_BOLD:
                    has_bold = True
                if flags & fitz.TEXT_FONT_ITALIC:
                    has_italic = True
                if not font_name:
                    font_name = span.get("font", "")

        text = "".join(text_parts).strip()
        if not text:
            return None

        # 如果整个块只有一行且明显是标题候选（大号加粗），先标记为 PARAGRAPH
        # level 字段暂存字号信息：level = int(font_size * 100)
        # 第二轮会根据全局统计做最终判定
        return ContentBlock(
            block_type=BlockType.PARAGRAPH,
            text=text,
            bold=has_bold,
            italic=has_italic,
            level=int(max_font_size * 100),  # 暂存字号
        )

    # ── 标题提升 ──

    @staticmethod
    def _promote_to_heading(cb: ContentBlock, median_size: float) -> None:
        """基于全局字号统计，将符合条件的段落提升为标题"""
        if median_size <= 0:
            return

        font_size = cb.level / 100.0  # 恢复暂存的字号
        ratio = font_size / median_size

        # 标题条件：字号 ≥ 中位数 1.15 倍 且 加粗
        if ratio < HEADING_FONT_RATIO or not cb.bold:
            cb.level = 0
            return

        # 根据比例确定标题层级
        if ratio >= HEADING_MIN_LEVEL_1_RATIO:
            cb.level = 1
        elif ratio >= HEADING_MIN_LEVEL_2_RATIO:
            cb.level = 2
        else:
            cb.level = 3

        cb.block_type = BlockType.HEADING
        cb.bold = False  # Markdown 标题自带加粗

    # ── 工具方法 ──

    @staticmethod
    def supported_extensions() -> list[str]:
        return [".pdf"]

    @staticmethod
    def _clean_text(text: str) -> str:
        """清理多余空白：合并连续换行，去除多余空格"""
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip()

    @staticmethod
    def _stitch_table_blocks(
        blocks: list[ContentBlock],
        page_heights: dict[int, float],
    ) -> list[ContentBlock]:
        originals = [
            block.table
            for block in blocks
            if block.block_type == BlockType.TABLE and block.table is not None
        ]
        stitched = _stitch_cross_page_tables(originals, page_heights)
        if len(stitched) == len(originals):
            return blocks

        replacements = {table.source_table_ids[0]: table for table in stitched}
        consumed = {
            table_id
            for table in stitched
            for table_id in table.source_table_ids[1:]
        }
        result: list[ContentBlock] = []
        for block in blocks:
            if block.block_type != BlockType.TABLE or block.table is None:
                result.append(block)
                continue
            table_id = block.table.table_id
            if table_id in consumed:
                continue
            replacement = replacements.get(table_id)
            result.append(
                ContentBlock(block_type=BlockType.TABLE, table=replacement)
                if replacement is not None
                else block
            )
        return result

    @staticmethod
    def _text_coverage(page) -> float:
        """Estimate usable text density; scanned pages approach zero."""
        try:
            character_count = len(page.get_text("text").strip())
            area_units = max(1.0, float(page.rect.width * page.rect.height) / 1000.0)
            return min(1.0, character_count / area_units)
        except Exception:
            return 0.0


def _stitch_cross_page_tables(
    tables: list[TableArtifact],
    page_heights: dict[int, float],
) -> list[TableArtifact]:
    if not tables:
        return []
    ordered = sorted(
        tables,
        key=lambda table: (
            table.page_number or 0,
            table.bbox.y0 if table.bbox else 0.0,
        ),
    )
    stitched: list[TableArtifact] = []
    previous_original: TableArtifact | None = None
    for table in ordered:
        if (
            stitched
            and previous_original is not None
            and _looks_like_continuation(previous_original, table, page_heights)
        ):
            stitched[-1] = _merge_continuation(stitched[-1], table)
        else:
            stitched.append(table)
        previous_original = table
    return stitched


def _looks_like_continuation(
    previous: TableArtifact,
    current: TableArtifact,
    page_heights: dict[int, float],
) -> bool:
    if previous.page_number is None or current.page_number != previous.page_number + 1:
        return False
    if previous.bbox is None or current.bbox is None:
        return False
    if previous.column_count != current.column_count:
        return False
    previous_height = page_heights.get(previous.page_number)
    current_height = page_heights.get(current.page_number)
    if not previous_height or not current_height:
        return False
    if previous.bbox.y1 < previous_height * 0.80 or current.bbox.y0 > current_height * 0.20:
        return False
    previous_headers = tuple(value.strip().casefold() for value in previous.legacy_headers())
    current_headers = tuple(value.strip().casefold() for value in current.legacy_headers())
    return bool(previous_headers and previous_headers == current_headers)


def _merge_continuation(first: TableArtifact, second: TableArtifact) -> TableArtifact:
    skip_rows = second.header_row_count
    shifted_cells = list(first.cells)
    for cell in second.cells:
        if cell.row_index < skip_rows:
            continue
        shifted_cells.append(cell.model_copy(update={
            "row_index": first.row_count + cell.row_index - skip_rows,
            "is_header": False,
        }))
    backend_scores = [
        score
        for score in (first.backend_confidence, second.backend_confidence)
        if score is not None
    ]
    return first.model_copy(update={
        "cells": shifted_cells,
        "row_count": first.row_count + second.row_count - skip_rows,
        "confidence": min(first.confidence, second.confidence),
        "backend_confidence": min(backend_scores) if backend_scores else None,
        "quality_score": min(
            score
            for score in (first.quality_score or first.confidence, second.quality_score or second.confidence)
        ),
        "quality_evidence": {
            **first.quality_evidence,
            "cross_page_parts": float(len(first.source_table_ids) + len(second.source_table_ids)),
        },
        "acceptance": (
            "accepted"
            if first.acceptance == second.acceptance == "accepted"
            else "review"
        ),
        "source_pages": list(dict.fromkeys(first.source_pages + second.source_pages)),
        "source_table_ids": first.source_table_ids + second.source_table_ids,
        "warnings": list(dict.fromkeys(first.warnings + second.warnings + ["cross_page_stitched"])),
    })

