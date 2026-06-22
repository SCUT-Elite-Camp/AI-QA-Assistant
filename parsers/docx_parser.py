"""
DOCX 解析器：使用 python-docx 提取文本、表格和结构信息。

特性:
- 表格提取：doc.iter_inner_content() 按文档顺序遍历 → Markdown 表格
- 结构检测：标题（style.name）、列表（numPr）、加粗（run.bold）
- 页眉页脚去除：iter_inner_content() 仅含正文 + 正则过滤残留模式
"""

import re
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中，支持直接运行此文件
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from docx import Document as DocxDocument
from models.document import Document, ContentBlock, BlockType
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
        for item in doc.iter_inner_content():
            # 判断是 Paragraph 还是 Table
            if hasattr(item, "style") and hasattr(item, "text"):
                # → Paragraph
                cb = self._paragraph_to_block(item)
                if cb is not None:
                    if not _is_page_number(cb.text):
                        all_blocks.append(cb)
            elif hasattr(item, "rows"):
                # → Table
                cb = self._table_to_block(item)
                if cb is not None:
                    all_blocks.append(cb)

        # ── 渲染为 Markdown ──
        content = "\n\n".join(
            cb.to_markdown() for cb in all_blocks if not cb.is_empty
        )
        if not content:
            content = ""

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
    def _table_to_block(table) -> ContentBlock | None:
        """将 python-docx Table 转为 ContentBlock"""
        all_rows: list[list[str]] = []
        for row in table.rows:
            cells: list[str] = []
            for cell in row.cells:
                # 单元格内可能有多段，用空格连接
                cell_text = cell.text.strip().replace("\n", " ")
                cells.append(cell_text)
            # 跳过全空行
            if any(c for c in cells):
                all_rows.append(cells)

        if not all_rows:
            return None

        # 首行作表头（常见约定——后续可增强为样式检测）
        headers = all_rows[0]
        body = all_rows[1:] if len(all_rows) > 1 else []

        return ContentBlock(
            block_type=BlockType.TABLE,
            headers=list(headers),
            rows=body,
        )

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


# ── 直接运行入口 ──
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python parsers/docx_parser.py <docx_file_path>")
        sys.exit(1)

    parser = DocxParser()
    doc = parser.parse(sys.argv[1])
    print(f"=== 文档: {doc.title} ===")
    print(f"doc_id: {doc.doc_id}")
    print(f"content_blocks 数量: {len(doc.content_blocks)}")
    for cb in doc.content_blocks:
        md = cb.to_markdown()
        if md:
            preview = md[:120].replace("\n", "\\n")
            print(f"  [{cb.block_type.value}] {preview}...")
    print(f"\n=== 全文 ({len(doc.content)} 字符) ===")
    print(doc.content[:2000])
