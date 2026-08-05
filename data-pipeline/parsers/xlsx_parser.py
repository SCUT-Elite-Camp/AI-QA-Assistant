"""
XLSX 解析器：使用 openpyxl 提取 Excel 工作簿中的所有单元格文字。

用途:
  - 独立解析 .xlsx 文件（Batch 模式，process.py 扫描）
  - 作为 Confluence 附件的内联解析器（HtmlParser 附件处理流程调用）

特性:
  - 遍历所有工作表 (sheet)
  - 按行提取单元格文本，保持表格结构
  - 空工作表自动跳过
  - 输出统一 Document / ContentBlock 模型
"""

from models.document import Document, ContentBlock, BlockType
from parsers.base import BaseParser


class XlsxParser(BaseParser):
    """使用 openpyxl 解析 XLSX 文件，提取所有单元格文字"""

    def parse(self, file_path: str) -> Document:
        import openpyxl

        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        all_blocks: list[ContentBlock] = []

        for sheet in wb.worksheets:
            sheet_name = sheet.title or "Sheet"
            sheet_blocks = self._parse_sheet(sheet, sheet_name)
            if sheet_blocks:
                all_blocks.extend(sheet_blocks)

        wb.close()

        # 渲染为 Markdown 全文
        content = "\n\n".join(
            cb.to_markdown() for cb in all_blocks if not cb.is_empty
        )
        content = self._clean_text(content)

        return Document.from_file_path(file_path, content, content_blocks=all_blocks)

    @staticmethod
    def _parse_sheet(sheet, sheet_name: str) -> list[ContentBlock]:
        """解析单个工作表，返回 ContentBlock 列表

        每个 non-empty 行作为一个 TABLE row，
        第一个 non-empty 行的 headers 被提取为表头。
        """
        blocks: list[ContentBlock] = []

        # 工作表标题作为 H2
        if sheet_name and sheet_name != "Sheet":
            blocks.append(ContentBlock(
                block_type=BlockType.HEADING,
                text=f"工作表: {sheet_name}",
                level=2,
            ))

        rows_data: list[list[str]] = []
        for row in sheet.iter_rows(values_only=True):
            if row is None:
                continue
            # 将单元格值转为字符串，空值留空
            cells = [
                str(cell).strip() if cell is not None else ""
                for cell in row
            ]
            # 跳过全空行
            if any(c for c in cells):
                rows_data.append(cells)

        if not rows_data:
            return []

        # 首行作表头，其余作数据行
        headers = rows_data[0]
        body = rows_data[1:] if len(rows_data) > 1 else []

        blocks.append(ContentBlock(
            block_type=BlockType.TABLE,
            headers=headers,
            rows=body,
        ))

        return blocks

    @staticmethod
    def supported_extensions() -> list[str]:
        return [".xlsx"]

    @staticmethod
    def _clean_text(text: str) -> str:
        import re
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip()
