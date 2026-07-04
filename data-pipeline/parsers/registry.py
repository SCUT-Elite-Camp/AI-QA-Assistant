import os
from parsers.base import BaseParser
from parsers.pdf_parser import PDFParser
from parsers.docx_parser import DocxParser
from models.document import Document

class DocumentParser:
    """
    统一的高层文档解析器类。
    对外提供统一的解析接口，解耦具体文件格式解析器细节。
    """
    def __init__(self, parsers: list[BaseParser] = None):
        self._parser_map: dict[str, BaseParser] = {}
        
        # 默认注册 PDFParser 和 DocxParser
        if parsers is None:
            parsers = [PDFParser(), DocxParser()]
            
        for p in parsers:
            self.register_parser(p)

    def register_parser(self, parser: BaseParser) -> None:
        """动态注册一个新的解析器实例"""
        for ext in parser.supported_extensions():
            self._parser_map[ext.lower()] = parser

    def get_parser(self, extension: str) -> BaseParser | None:
        """根据文件扩展名获取解析器实例"""
        return self._parser_map.get(extension.lower())

    def parse(self, file_path: str) -> Document:
        """核心解析方法：根据文件后缀自动选择对应的解析器"""
        ext = os.path.splitext(file_path)[1].lower()
        parser = self.get_parser(ext)
        if parser is None:
            raise ValueError(f"不支持的文件类型: {ext}（文件: {file_path}）")
        return parser.parse(file_path)

    @property
    def supported_extensions(self) -> list[str]:
        """返回所有已注册的支持的文件扩展名列表"""
        return list(self._parser_map.keys())

# 默认的全局解析器实例（保持向下兼容）
_default_parser = DocumentParser()

def get_parser(extension: str) -> BaseParser | None:
    """根据文件扩展名获取对应的解析器实例，不支持返回 None（向下兼容）"""
    return _default_parser.get_parser(extension)

def parse_file(file_path: str) -> Document:
    """一站式解析入口：根据扩展名自动选择解析器（向下兼容）"""
    return _default_parser.parse(file_path)

def supported_extensions() -> list[str]:
    """返回所有已注册的文件扩展名（向下兼容）"""
    return _default_parser.supported_extensions
