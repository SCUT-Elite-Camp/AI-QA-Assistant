"""
DOCX 解析器：使用 python-docx 提取文本、表格和结构信息。

特性:
- 表格提取：doc.iter_inner_content() 按文档顺序遍历 → Markdown 表格
- 结构检测：标题（style.name）、列表（numPr）、加粗（run.bold）
- 页眉页脚去除：iter_inner_content() 仅含正文 + 正则过滤残留模式
"""

import re

from docx import Document as DocxDocument
from docx.oxml.ns import qn
from models.document import Document, ContentBlock, BlockType, TableArtifact, TableCell
from parsers.base import BaseParser

# ── 常见页眉页脚模式 ──
_HEADER_FOOTER_PATTERNS: list[re.Pattern] = [
    re.compile(r"^第\s*\d+\s*页\s*$"),            # "第X页"
    re.compile(r"^第\s*\d+\s*页\s*共\s*\d+\s*页\s*$"),  # "第X页共Y页"
    re.compile(r"^Page\s*\d+(\s*of\s*\d+)?$", re.IGNORECASE),
    re.compile(r"^\d{1,3}$"),                     # 纯页码
    re.compile(r"^-\s*\d+\s*-$"),                 # "- 1 -"
]

class DocxParser(BaseParser):
    """使用 python-docx 解析 DOCX 文件，提取表格和结构信息"""

    def parse(self, file_path: str) -> Document:
        doc = DocxDocument(file_path)
        all_blocks: list[ContentBlock] = []

        # iter_inner_content() 按文档顺序产出 Paragraph 和 Table
        # 优点：保持正文中段落与表格的交错顺序
        table_index = 0
        page = 1
        embedded_image = 0
        for block_index, item in enumerate(doc.iter_inner_content()):
            before = len(all_blocks)
            # 判断是 Paragraph 还是 Table
            if hasattr(item, "style") and hasattr(item, "text"):
                # → Paragraph
                cb = self._paragraph_to_block(item)
                if cb is not None:
                    if not _is_page_number(cb.text):
                        all_blocks.append(cb)
            elif hasattr(item, "rows"):
                # → Table
                table_index += 1
                cb = self._table_to_block(item, table_index)
                if cb is not None:
                    all_blocks.append(cb)
            for block in all_blocks[before:]:
                block.page_number = page
                block.locator = {**block.locator, "page": page, "block": block_index}
            element = getattr(item, '_p', None)
            if element is None:
                element = getattr(item, '_tbl', None)
            if element is not None:
                for descendant in element.iter():
                    if descendant.tag == qn('w:br') and descendant.get(qn('w:type')) == 'page':
                        page += 1
                    if descendant.tag != qn('a:blip'):
                        continue
                    relationship_id = descendant.get(qn('r:embed'))
                    related_part = doc.part.related_parts.get(relationship_id)
                    blob = getattr(related_part, 'blob', None)
                    if blob:
                        from parsers.upload_formats import image_blocks
                        embedded_image += 1
                        all_blocks.extend(image_blocks(blob, {
                            "page": page, "block": block_index, "embedded_image": embedded_image,
                        }))

        # ── 渲染为 Markdown ──
        content = "\n\n".join(
            cb.to_markdown() for cb in all_blocks if not cb.is_empty
        )

        return Document.from_file_path(file_path, content, content_blocks=all_blocks)

    # ── 段落转换 ──

    @staticmethod
    def _paragraph_to_block(para) -> ContentBlock | None:
        """将 python-docx Paragraph 转为 ContentBlock"""
        text = para.text.strip()
        if not text:
            return None

        style_name = para.style.name if para.style else ""

        # 1. 标题检测：style.name 以 "Heading" 或 "heading" 开头
        if _is_heading_style(style_name):
            level = _heading_level(style_name)
            return ContentBlock(
                block_type=BlockType.HEADING,
                text=text,
                level=min(level, 6),
            )

        # 2. 列表检测：通过底层 XML 的 numPr 元素
        if _has_numbering(para):
            return ContentBlock(
                block_type=BlockType.LIST,
                text=text,
            )

        # 3. 常规段落（检测加粗/斜体）
        is_bold = any(run.bold for run in para.runs if run.bold)
        is_italic = any(run.italic for run in para.runs if run.italic)

        return ContentBlock(
            block_type=BlockType.PARAGRAPH,
            text=text,
            bold=is_bold,
            italic=is_italic,
        )

    # ── 表格转换 ──

    @staticmethod
    def _table_to_block(table, table_index: int) -> ContentBlock | None:
        """Read native DOCX merge XML into a canonical TableArtifact."""
        row_count = len(table._tbl.tr_lst)
        if row_count == 0:
            return None

        grid = table._tbl.tblGrid
        column_count = len(grid.gridCol_lst) if grid is not None else 0
        cells: list[TableCell] = []
        active_vertical: dict[int, int] = {}
        bold_by_row: list[tuple[int, int]] = []
        explicit_header_rows: set[int] = set()

        for row_index, tr in enumerate(table._tbl.tr_lst):
            if tr.trPr is not None and tr.trPr.find(qn("w:tblHeader")) is not None:
                explicit_header_rows.add(row_index)
            column_index = 0
            bold_cells = 0
            nonempty_cells = 0
            extended_starts: set[int] = set()

            for tc in tr.tc_lst:
                tc_pr = tc.tcPr
                grid_span = tc_pr.gridSpan if tc_pr is not None else None
                column_span = int(grid_span.val) if grid_span is not None else 1
                v_merge = tc_pr.vMerge if tc_pr is not None else None
                merge_value = v_merge.val if v_merge is not None else None
                is_continuation = v_merge is not None and merge_value != "restart"
                text = " ".join(
                    value.strip()
                    for value in (node.text or "" for node in tc.iter(qn("w:t")))
                    if value.strip()
                )

                if is_continuation and column_index in active_vertical:
                    start_index = active_vertical[column_index]
                    if start_index not in extended_starts:
                        cells[start_index].row_span += 1
                        extended_starts.add(start_index)
                else:
                    for covered_column in range(column_index, column_index + column_span):
                        active_vertical.pop(covered_column, None)
                    cell = TableCell(
                        row_index=row_index,
                        column_index=column_index,
                        text=text,
                        column_span=column_span,
                    )
                    cells.append(cell)
                    start_index = len(cells) - 1
                    if v_merge is not None and merge_value == "restart":
                        for covered_column in range(column_index, column_index + column_span):
                            active_vertical[covered_column] = start_index

                if text:
                    nonempty_cells += 1
                    if tc.xpath(".//w:b[not(@w:val='0') and not(@w:val='false')]"):
                        bold_cells += 1
                column_index += column_span
                column_count = max(column_count, column_index)

            bold_by_row.append((bold_cells, nonempty_cells))

        if not any(cell.text for cell in cells):
            return None

        header_row_count = 0
        for row_index, (bold_cells, nonempty_cells) in enumerate(bold_by_row):
            explicit = row_index in explicit_header_rows
            mostly_bold = nonempty_cells > 0 and bold_cells / nonempty_cells >= 0.5
            if explicit or mostly_bold:
                header_row_count += 1
            else:
                break

        for cell in cells:
            cell.is_header = cell.row_index < header_row_count

        artifact = TableArtifact(
            table_id=f"docx-table-{table_index}",
            cells=cells,
            row_count=row_count,
            column_count=column_count,
            header_row_count=header_row_count,
            parser_name="docx",
            confidence=0.95,
            backend_confidence=0.95,
            quality_score=0.95,
            quality_evidence={"native_structure": 1.0},
            acceptance="accepted",
        )
        return ContentBlock(block_type=BlockType.TABLE, table=artifact)

    # ── 工具 ──

    @staticmethod
    def supported_extensions() -> list[str]:
        return [".docx"]

# ── 辅助函数 ──

def _is_heading_style(style_name: str) -> bool:
    """判断样式名是否表示标题"""
    if not style_name:
        return False
    lower = style_name.lower()
    return lower.startswith("heading") or "标题" in lower or lower.startswith("title")

def _heading_level(style_name: str) -> int:
    """从样式名中提取标题层级（1-9）"""
    # 尝试匹配 "Heading 1", "heading 2" 等
    match = re.search(r"(\d+)", style_name)
    if match:
        return int(match.group(1))
    # "Title" 样式视为一级标题
    if "title" in style_name.lower():
        return 1
    return 1

def _has_numbering(para) -> bool:
    """判断段落是否有列表编号（通过 w:numPr 元素）"""
    try:
        pPr = para._element.pPr
        if pPr is not None:
            numPr = pPr.numPr
            if numPr is not None and numPr.numId is not None:
                return numPr.numId.val is not None
    except Exception:
        pass
    return False

def _is_page_number(text: str) -> bool:
    """判断文本是否看起来像页码或页眉页脚文本"""
    for pat in _HEADER_FOOTER_PATTERNS:
        if pat.match(text):
            return True
    return False

