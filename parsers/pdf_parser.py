"""
PDF 解析器：使用 PyMuPDF 提取文本、表格和结构信息。

特性:
- 表格提取：page.find_tables() → Markdown 表格
- 页眉页脚去除：按 y 坐标过滤（上下各 15%）
- 标题检测：基于字体大小和加粗的启发式推断（PDF 无语义标题信息）
- 结构保留：输出 ContentBlock 列表 + 渲染 Markdown
"""

import re
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中，支持直接运行此文件
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import fitz  # pymupdf
from models.document import Document, ContentBlock, BlockType
from parsers.base import BaseParser

# ── 配置常量 ──
HEADER_FOOTER_RATIO = 0.15       # 页面上/下边缘区域比例
HEADING_FONT_RATIO = 1.15        # 字号超过正文中位数此倍数视为候选标题
HEADING_MIN_LEVEL_1_RATIO = 1.5  # 一级标题的最低字号比例
HEADING_MIN_LEVEL_2_RATIO = 1.3  # 二级标题的最低字号比例


class PDFParser(BaseParser):
    """使用 PyMuPDF 解析 PDF 文件，提取表格、结构信息并去除页眉页脚"""

    def parse(self, file_path: str) -> Document:
        pdf_doc = fitz.open(file_path)
        all_blocks: list[ContentBlock] = []
        body_font_sizes: list[float] = []

        # ── 第一轮：逐页提取内容块和正文字号 ──
        for page in pdf_doc:
            page_height = page.rect.height
            header_y = page_height * HEADER_FOOTER_RATIO
            footer_y = page_height * (1 - HEADER_FOOTER_RATIO)

            # 1. 提取表格区域（用于后续排除文本块中的表格文字）
            table_regions = self._extract_table_regions(page)
            tables = page.find_tables()

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

            # 3. 提取表格内容块（用表格顶部作为 y 位置）
            for table in tables:
                cb = self._table_to_content_block(table)
                if cb:
                    try:
                        table_y = table.bbox[1]  # 表格顶部 y 坐标
                    except Exception:
                        table_y = 0.0
                    positioned.append((table_y, cb))

            # 4. 按垂直位置排序，保持阅读顺序
            positioned.sort(key=lambda item: item[0])
            all_blocks.extend(cb for _, cb in positioned)

        pdf_doc.close()

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
        if not content:
            content = ""

        return Document.from_file_path(file_path, content, content_blocks=all_blocks)

    # ── 区域与重叠判断 ──

    @staticmethod
    def _extract_table_regions(page) -> list[tuple[float, float, float, float]]:
        """获取页面上所有表格的边界框"""
        regions: list[tuple[float, float, float, float]] = []
        try:
            tables = page.find_tables()
            for t in tables:
                try:
                    regions.append(tuple(t.bbox))
                except Exception:
                    pass
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

    # ── 表格转换 ──

    @staticmethod
    def _table_to_content_block(table) -> ContentBlock | None:
        """将 PyMuPDF Table 对象转为 ContentBlock"""
        try:
            extracted = table.extract()
            if not extracted or len(extracted) == 0:
                return None
            # 首行作表头
            headers = [str(c or "") for c in extracted[0]]
            body = [[str(c or "") for c in row] for row in extracted[1:]]
            if not body:
                body = [[str(c or "") for c in row] for row in extracted]
                headers = []
            return ContentBlock(
                block_type=BlockType.TABLE,
                headers=headers,
                rows=body,
            )
        except Exception:
            return None

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


# ── 直接运行入口 ──
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python parsers/pdf_parser.py <pdf_file_path>")
        sys.exit(1)

    parser = PDFParser()
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
