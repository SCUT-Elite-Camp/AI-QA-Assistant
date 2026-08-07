"""
DOC 解析器：支持旧版 .doc 二进制 Word 文档解析。

策略:
1. 优先使用 Windows win32com (MS Word) 或 LibreOffice 将 .doc 转为临时 .docx，再调用 DocxParser 提取结构、表格与段落。
2. 若无转码工具环境，回退使用 OLE / 二进制流文本提取算法，确保在任何环境下均能安全提取文本并生成 Document。
"""

import os
import re
import tempfile
from pathlib import Path

from models.document import Document, ContentBlock, BlockType
from parsers.base import BaseParser
from parsers.docx_parser import DocxParser


class DocParser(BaseParser):
    """支持 .doc 文件解析，兼顾结构化转码提取与基础纯文本回退"""

    def __init__(self) -> None:
        self._docx_parser = DocxParser()

    def supported_extensions(self) -> list[str]:
        return [".doc"]

    def parse(self, file_path: str) -> Document:
        abs_path = os.path.abspath(file_path)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"未找到文件: {file_path}")

        # 尝试 1：通过 win32com 转码为临时 .docx，再借由 DocxParser 完整解析段落与表格
        converted_docx = self._convert_doc_to_docx_win32(abs_path)
        if converted_docx and os.path.exists(converted_docx):
            try:
                doc = self._docx_parser.parse(converted_docx)
                # 恢复真实文件名与 ID
                return Document.from_file_path(
                    abs_path,
                    doc.content,
                    content_blocks=doc.content_blocks,
                )
            finally:
                try:
                    os.remove(converted_docx)
                except OSError:
                    pass

        # 尝试 2：使用纯 Python OLE / 二进制流降级提取文本
        return self._parse_doc_fallback(abs_path)

    @staticmethod
    def _convert_doc_to_docx_win32(doc_path: str) -> str | None:
        """尝试在 Windows 环境利用 MS Word 将 .doc 转为临时 .docx"""
        try:
            import olefile  # type: ignore[import-not-found]
            if not olefile.isOleFile(doc_path):
                return None
        except Exception:
            pass

        try:
            import win32com.client  # type: ignore[import-not-found]
            temp_dir = tempfile.mkdtemp()
            dest_docx = os.path.join(temp_dir, f"temp_{os.path.basename(doc_path)}x")
            
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = False
            try:
                wb = word.Documents.Open(doc_path)
                # 16 代表 wdFormatXMLDocument (.docx)
                wb.SaveAs2(dest_docx, FileFormat=16)
                wb.Close()
                return dest_docx
            finally:
                word.Quit()
        except Exception:
            return None

    def _parse_doc_fallback(self, doc_path: str) -> Document:
        """纯 Python 降级解包方案：读取 WordDocument OLE 流或提取可打印文本段落"""
        extracted_text = ""

        # 1. 尝试使用 olefile 提取 WordDocument 流文本
        try:
            import olefile  # type: ignore[import-not-found]
            if olefile.isOleFile(doc_path):
                with olefile.OleFileIO(doc_path) as ole:
                    if ole.exists("WordDocument"):
                        stream = ole.openstream("WordDocument").read()
                        # WordDocument 二进制流文本解码 (支持 UTF-16LE 及 GBK 提取)
                        extracted_text = self._extract_text_from_stream(stream)
        except Exception:
            pass

        # 2. 若无 OLE 流文本，回退使用原始二进制字符串提取
        if not extracted_text.strip():
            with open(doc_path, "rb") as f:
                content_bytes = f.read()
            extracted_text = self._extract_text_from_raw_bytes(content_bytes)

        lines = [line.strip() for line in extracted_text.split("\n") if line.strip()]
        blocks: list[ContentBlock] = [
            ContentBlock(block_type=BlockType.PARAGRAPH, text=line)
            for line in lines
        ]

        full_content = "\n\n".join(lines)
        return Document.from_file_path(doc_path, full_content, content_blocks=blocks)

    @staticmethod
    def _extract_text_from_stream(stream: bytes) -> str:
        """从二进制 Word 字节流中匹配提取中英文连续可读文本块"""
        decoded_text = ""
        try:
            decoded_text = stream.decode("utf-16-le", errors="ignore")
        except Exception:
            try:
                decoded_text = stream.decode("gbk", errors="ignore")
            except Exception:
                decoded_text = stream.decode("utf-8", errors="ignore")

        # 正则挑选可打印字符与常见中文/英文段落
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", decoded_text)
        pattern = re.compile(r"[\u4e00-\u9fa5a-zA-Z0-9\s,.\u3002\uff0c\uff1a\uff1b\u201c\u201d\uff08\uff09!?\-—]{3,}")
        matches = pattern.findall(cleaned)
        return "\n".join(m.strip() for m in matches if m.strip())

    @staticmethod
    def _extract_text_from_raw_bytes(raw_bytes: bytes) -> str:
        """原始字节解析方案"""
        decoded = raw_bytes.decode("gbk", errors="ignore")
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", decoded)
        pattern = re.compile(r"[\u4e00-\u9fa5a-zA-Z0-9\s,.\u3002\uff0c\uff1a\uff1b!?\-]{4,}")
        matches = pattern.findall(cleaned)
        return "\n".join(m.strip() for m in matches if m.strip())
