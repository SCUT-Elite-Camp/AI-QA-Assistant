"""
PDF 解析器：使用 PyMuPDF 提取文本、表格和结构信息。

特性:
- 表格提取：page.find_tables() → Markdown 表格
- 页眉页脚去除：跨页重复边缘内容检测
- 标题检测：基于字体大小和加粗的启发式推断（PDF 无语义标题信息）
- 结构保留：输出带版面来源的 ContentBlock 列表 + 渲染 Markdown
"""

import re
import unicodedata
from dataclasses import replace

import pymupdf as fitz
from models.document import (
    BlockType,
    ContentBlock,
    Document,
    PageRegion,
    ParseDiagnostics,
    TableArtifact,
)
from parsers.base import BaseParser
from parsers.ocr_backends import (
    PageOCRBackend,
    PageTextQuality,
    PyMuPDFOCRBackend,
    evaluate_page_text_quality,
)
from parsers.pdf_layout import (
    LayoutBlock,
    LayoutDiagnostics,
    extract_layout_blocks,
    filter_repeated_edge_blocks,
    find_repeated_edge_keys,
    order_layout_blocks,
)
from parsers.table_backends import (
    CamelotTableBackend,
    GMFTTableBackend,
    PaddleOCRTableBackend,
    PyMuPDFTableBackend,
)
from parsers.table_router import TableRouter

# ── 配置常量 ──
HEADING_FONT_RATIO = 1.15        # 字号超过正文中位数此倍数视为候选标题
HEADING_LARGE_FONT_RATIO = 1.25  # 非粗体大字号也可作为标题候选
HEADING_MIN_LEVEL_1_RATIO = 1.5  # 一级标题的最低字号比例
HEADING_MIN_LEVEL_2_RATIO = 1.3  # 二级标题的最低字号比例
MIN_RELIABLE_NATIVE_CHARACTERS = 4
OCR_DUPLICATE_REGION_OVERLAP = 0.50

class PDFParser(BaseParser):
    """使用 PyMuPDF 解析 PDF 文件，提取表格、结构信息并去除页眉页脚"""

    def __init__(
        self,
        router: TableRouter | None = None,
        ocr_backend: PageOCRBackend | None = None,
    ):
        self.table_router = router or TableRouter(
            PyMuPDFTableBackend(),
            CamelotTableBackend(),
            PaddleOCRTableBackend(),
            complex_fallback=GMFTTableBackend(),
        )
        self.ocr_backend = ocr_backend if ocr_backend is not None else PyMuPDFOCRBackend()
        self.last_layout_diagnostics = LayoutDiagnostics()

    def parse(self, file_path: str) -> Document:
        pdf_doc = fitz.open(file_path)
        all_blocks: list[ContentBlock] = []
        body_font_sizes: list[float] = []
        page_heights: dict[int, float] = {}
        source_tables: dict[str, TableArtifact] = {}
        page_count = len(pdf_doc)
        table_messages_by_page: dict[int, list[str]] = {}
        try:
            # Pass one gathers native text without deleting edge content so
            # repetition can be evaluated across the complete document.
            layout_pages: list[list[LayoutBlock]] = []
            ocr_diagnostics = LayoutDiagnostics()
            for page_number, page in enumerate(pdf_doc, start=1):
                native_blocks = extract_layout_blocks(page, page_number)
                quality = evaluate_page_text_quality(page, native_blocks)
                selected_blocks = native_blocks
                if quality.needs_ocr:
                    selected_blocks = self._select_page_text(
                        page,
                        page_number,
                        native_blocks,
                        quality,
                        ocr_diagnostics,
                    )
                layout_pages.append(selected_blocks)
            repeated_edge_keys = find_repeated_edge_keys(layout_pages)
            layout_pages, diagnostics = filter_repeated_edge_blocks(
                layout_pages,
                repeated_edge_keys,
            )
            diagnostics.ocr_attempted_pages = ocr_diagnostics.ocr_attempted_pages
            diagnostics.ocr_applied_pages = ocr_diagnostics.ocr_applied_pages
            diagnostics.ocr_unavailable_pages = ocr_diagnostics.ocr_unavailable_pages
            diagnostics.ocr_failed_pages = ocr_diagnostics.ocr_failed_pages
            diagnostics.ocr_empty_pages = ocr_diagnostics.ocr_empty_pages
            diagnostics.ocr_not_improved_pages = ocr_diagnostics.ocr_not_improved_pages
            diagnostics.ocr_messages = ocr_diagnostics.ocr_messages
            self.last_layout_diagnostics = diagnostics

            # Pass two reconciles accepted tables and reconstructs page order.
            for page_index, page in enumerate(pdf_doc, start=1):
                page_width = float(page.rect.width)
                page_height = float(page.rect.height)
                page_heights[page_index] = page_height
                artifacts = self.table_router.route_page(
                    page,
                    page_number=page_index,
                    text_coverage=self._text_coverage(page),
                    file_path=file_path,
                )
                raw_table_messages = getattr(self.table_router, "last_diagnostics", [])
                if isinstance(raw_table_messages, str):
                    raw_table_messages = [raw_table_messages]
                if isinstance(raw_table_messages, (list, tuple)):
                    messages = list(dict.fromkeys(
                        str(message)
                        for message in raw_table_messages
                        if message not in (None, "")
                    ))
                    if messages:
                        table_messages_by_page[page_index] = messages
                source_tables.update({artifact.table_id: artifact for artifact in artifacts})
                ordered_inputs = list(layout_pages[page_index - 1])
                table_by_layout_id: dict[int, TableArtifact] = {}
                next_ordinal = max((block.ordinal for block in ordered_inputs), default=-1) + 1
                for artifact_index, artifact in enumerate(artifacts):
                    if artifact.bbox is None:
                        bbox = (0.0, 0.0, page_width, 0.0)
                    else:
                        bbox = (
                            artifact.bbox.x0,
                            artifact.bbox.y0,
                            artifact.bbox.x1,
                            artifact.bbox.y1,
                        )
                    table_layout = LayoutBlock(
                        text="",
                        bbox=bbox,
                        font_size=0.0,
                        font_name="",
                        flags=0,
                        rotation=0.0,
                        page_number=page_index,
                        ordinal=next_ordinal + artifact_index,
                        page_width=page_width,
                        page_height=page_height,
                        confidence=artifact.confidence,
                        extraction_method=artifact.parser_name,
                    )
                    ordered_inputs.append(table_layout)
                    table_by_layout_id[id(table_layout)] = artifact

                for block in order_layout_blocks(ordered_inputs, page_width):
                    artifact = table_by_layout_id.get(id(block))
                    all_blocks.append(
                        _table_to_content_block(artifact)
                        if artifact is not None
                        else block.to_content_block()
                    )
        finally:
            pdf_doc.close()

        # Merge only strict, high-signal continuations: adjacent pages, same
        # columns/headers, previous table at page bottom and next at page top.
        all_blocks = self._stitch_table_blocks(all_blocks, page_heights)
        all_blocks = self._exclude_text_overlapping_accepted_tables(
            all_blocks,
            source_tables,
            diagnostics,
        )
        body_font_sizes = [
            block.font_size
            for block in all_blocks
            if block.block_type != BlockType.TABLE and block.font_size > 0
        ]

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
            rendered
            for cb in all_blocks
            if not cb.is_empty
            for rendered in (cb.to_index_markdown(),)
            if rendered
        )
        content = self._clean_text(content)

        final_tables = [
            block.table
            for block in all_blocks
            if block.block_type == BlockType.TABLE and block.table is not None
        ]
        parse_diagnostics = ParseDiagnostics(
            parser_name="pdf",
            page_count=page_count,
            removed_headers=diagnostics.removed_headers,
            removed_footers=diagnostics.removed_footers,
            partial_table_overlaps=diagnostics.partial_table_overlaps,
            ocr_attempted_pages=diagnostics.ocr_attempted_pages,
            ocr_applied_pages=diagnostics.ocr_applied_pages,
            ocr_unavailable_pages=diagnostics.ocr_unavailable_pages,
            ocr_failed_pages=diagnostics.ocr_failed_pages,
            ocr_empty_pages=diagnostics.ocr_empty_pages,
            ocr_not_improved_pages=diagnostics.ocr_not_improved_pages,
            ocr_messages=diagnostics.ocr_messages,
            table_messages_by_page=table_messages_by_page,
            accepted_tables=sum(table.acceptance == "accepted" for table in final_tables),
            review_tables=sum(table.acceptance == "review" for table in final_tables),
        )
        return Document.from_file_path(
            file_path,
            content,
            content_blocks=all_blocks,
            parse_diagnostics=parse_diagnostics,
        )

    # ── 区域与重叠判断 ──

    def _select_page_text(
        self,
        page,
        page_number: int,
        native_blocks: list[LayoutBlock],
        native_quality: PageTextQuality,
        diagnostics: LayoutDiagnostics,
    ) -> list[LayoutBlock]:
        """Use OCR only for a weak page and keep native text on any failure."""
        try:
            available = self.ocr_backend.available()
        except Exception as error:
            diagnostics.ocr_failed_pages.append(page_number)
            diagnostics.ocr_messages.append(
                f"page {page_number}: OCR availability check failed: {error}"
            )
            return native_blocks
        if not available:
            diagnostics.ocr_unavailable_pages.append(page_number)
            diagnostics.ocr_messages.append(
                f"page {page_number}: OCR unavailable for low-quality native text "
                f"({', '.join(native_quality.reasons)})"
            )
            return native_blocks

        diagnostics.ocr_attempted_pages.append(page_number)
        try:
            ocr_blocks = self.ocr_backend.extract(page, page_number)
        except Exception as error:
            diagnostics.ocr_failed_pages.append(page_number)
            diagnostics.ocr_messages.append(f"page {page_number}: OCR failed: {error}")
            return native_blocks

        selected = _ocr_content_to_layout_blocks(ocr_blocks, page, page_number)
        if not selected:
            diagnostics.ocr_empty_pages.append(page_number)
            diagnostics.ocr_messages.append(f"page {page_number}: OCR returned no usable text")
            return native_blocks
        selected = _fuse_native_and_ocr_blocks(
            native_blocks,
            selected,
            float(page.rect.width),
        )
        ocr_quality = evaluate_page_text_quality(page, selected)
        if _page_text_rank(ocr_quality) <= _page_text_rank(native_quality):
            diagnostics.ocr_not_improved_pages.append(page_number)
            diagnostics.ocr_messages.append(
                f"page {page_number}: OCR did not improve native text quality"
            )
            return native_blocks
        diagnostics.ocr_applied_pages.append(page_number)
        return selected

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
        """Return whether a table covers at least half of the text block."""
        return max((_overlap_ratio(bbox, region) for region in regions), default=0.0) >= 0.50

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

        font_size = cb.font_size or cb.level / 100.0
        ratio = font_size / median_size

        # Preserve the existing font-size-plus-bold signal while allowing a
        # sufficiently large face to identify headings without a bold flag.
        if ratio < HEADING_LARGE_FONT_RATIO and not (
            cb.bold and ratio >= HEADING_FONT_RATIO
        ):
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
                _table_to_content_block(replacement)
                if replacement is not None
                else block
            )
        return result

    @staticmethod
    def _exclude_text_overlapping_accepted_tables(
        blocks: list[ContentBlock],
        source_tables: dict[str, TableArtifact],
        diagnostics: LayoutDiagnostics,
    ) -> list[ContentBlock]:
        """Drop text only for tables that remain accepted after stitching."""
        regions_by_page: dict[int, list[tuple[float, float, float, float]]] = {}
        for block in blocks:
            table = block.table
            if table is None or table.acceptance != "accepted":
                continue
            regions = list(table.page_regions)
            if not regions:
                regions = [
                    PageRegion(
                        page_number=source.page_number,
                        bbox=source.bbox,
                        table_ids=[source.table_id],
                        sources=["table"],
                        confidence=source.confidence,
                    )
                    for table_id in table.source_table_ids
                    for source in [source_tables.get(table_id)]
                    if source is not None and source.page_number is not None and source.bbox is not None
                ]
            for region in regions:
                regions_by_page.setdefault(region.page_number, []).append((
                    region.bbox.x0,
                    region.bbox.y0,
                    region.bbox.x1,
                    region.bbox.y1,
                ))

        retained: list[ContentBlock] = []
        for block in blocks:
            if block.block_type == BlockType.TABLE or block.bbox is None or block.page_number is None:
                retained.append(block)
                continue
            overlap = max(
                (_overlap_ratio(
                    (block.bbox.x0, block.bbox.y0, block.bbox.x1, block.bbox.y1),
                    region,
                ) for region in regions_by_page.get(block.page_number, [])),
                default=0.0,
            )
            if overlap >= 0.50:
                continue
            if overlap > 0.0:
                diagnostics.partial_table_overlaps += 1
            retained.append(block)
        return retained

    @staticmethod
    def _text_coverage(page) -> float:
        """Estimate usable text density; scanned pages approach zero."""
        try:
            character_count = len(page.get_text("text").strip())
            area_units = max(1.0, float(page.rect.width * page.rect.height) / 1000.0)
            return min(1.0, character_count / area_units)
        except Exception:
            return 0.0


def _ocr_content_to_layout_blocks(
    blocks: list[ContentBlock],
    page,
    page_number: int,
) -> list[LayoutBlock]:
    """Normalize backend OCR output for shared filtering and page ordering."""
    page_width = float(page.rect.width)
    page_height = float(page.rect.height)
    result: list[LayoutBlock] = []
    for block in blocks:
        if not block.text.strip() or block.bbox is None:
            continue
        flags = 0
        if block.bold:
            flags |= fitz.TEXT_FONT_BOLD
        if block.italic:
            flags |= fitz.TEXT_FONT_ITALIC
        result.append(LayoutBlock(
            text=block.text,
            bbox=(block.bbox.x0, block.bbox.y0, block.bbox.x1, block.bbox.y1),
            font_size=block.font_size,
            font_name=block.font_name,
            flags=flags,
            rotation=block.rotation,
            page_number=page_number,
            ordinal=len(result),
            page_width=page_width,
            page_height=page_height,
            confidence=block.confidence,
            extraction_method="ocr",
            source="ocr",
        ))
    return result


def _fuse_native_and_ocr_blocks(
    native_blocks: list[LayoutBlock],
    ocr_blocks: list[LayoutBlock],
    page_width: float,
) -> list[LayoutBlock]:
    """Keep reliable native text and supplement only non-overlapping OCR."""
    reliable_native = [block for block in native_blocks if _reliable_native_text(block.text)]
    if reliable_native:
        ocr_blocks = [
            ocr_block
            for ocr_block in ocr_blocks
            if not any(
                _layout_overlap_ratio(ocr_block.bbox, native_block.bbox)
                >= OCR_DUPLICATE_REGION_OVERLAP
                for native_block in reliable_native
            )
        ]
        selected = [*reliable_native, *ocr_blocks]
    else:
        selected = list(ocr_blocks)
    ordered = order_layout_blocks(selected, page_width)
    return [replace(block, ordinal=index) for index, block in enumerate(ordered)]


def _reliable_native_text(text: str) -> bool:
    characters = [character for character in text if not character.isspace()]
    if len(characters) < MIN_RELIABLE_NATIVE_CHARACTERS:
        return False
    invalid = sum(
        character == "\ufffd" or unicodedata.category(character).startswith("C")
        for character in characters
    )
    return invalid / len(characters) < 0.10


def _layout_overlap_ratio(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    first_x0, first_y0, first_x1, first_y1 = first
    second_x0, second_y0, second_x1, second_y1 = second
    intersection = (
        max(0.0, min(first_x1, second_x1) - max(first_x0, second_x0))
        * max(0.0, min(first_y1, second_y1) - max(first_y0, second_y0))
    )
    first_area = max(0.0, first_x1 - first_x0) * max(0.0, first_y1 - first_y0)
    second_area = max(0.0, second_x1 - second_x0) * max(0.0, second_y1 - second_y0)
    smaller_area = min(first_area, second_area)
    return intersection / smaller_area if smaller_area > 0 else 0.0


def _page_text_rank(quality: PageTextQuality) -> tuple[bool, int, float]:
    """Rank text streams deterministically, preferring valid then fuller text."""
    invalid = {"replacement_characters", "control_characters"}
    contains_invalid_characters = bool(invalid.intersection(quality.reasons))
    return (
        not contains_invalid_characters,
        quality.usable_character_count,
        quality.usable_character_density,
    )


def _overlap_ratio(
    block_bbox: tuple[float, float, float, float],
    table_bbox: tuple[float, float, float, float],
) -> float:
    """Return the fraction of a text block covered by a table rectangle."""
    bx0, by0, bx1, by1 = block_bbox
    tx0, ty0, tx1, ty1 = table_bbox
    x0 = max(bx0, tx0)
    y0 = max(by0, ty0)
    x1 = min(bx1, tx1)
    y1 = min(by1, ty1)
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    block_area = max(1.0, (bx1 - bx0) * (by1 - by0))
    return intersection / block_area


def _table_to_content_block(table: TableArtifact) -> ContentBlock:
    """Synchronize canonical table provenance onto its content block."""
    return ContentBlock(
        block_type=BlockType.TABLE,
        block_id=table.table_id,
        page_number=table.page_number,
        bbox=table.bbox,
        confidence=table.confidence,
        source="table",
        extraction_method=table.parser_name,
        table=table,
    )


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
        "page_regions": [*first.page_regions, *second.page_regions],
        "warnings": list(dict.fromkeys(first.warnings + second.warnings + ["cross_page_stitched"])),
    })

