import os
from parsers.base import BaseParser
from parsers.pdf_parser import PDFParser
from parsers.docx_parser import DocxParser
from models.document import Document


# 扩展名 → 解析器实例 映射
_PARSER_MAP: dict[str, BaseParser] = {}

_parsers = [PDFParser(), DocxParser()]
for _p in _parsers:
    for _ext in _p.supported_extensions():
        _PARSER_MAP[_ext.lower()] = _p


def get_parser(extension: str) -> BaseParser | None:
    """根据文件扩展名获取对应的解析器实例，不支持返回 None"""
    return _PARSER_MAP.get(extension.lower())


def parse_file(file_path: str) -> Document:
    """一站式解析入口：根据扩展名自动选择解析器"""
    ext = os.path.splitext(file_path)[1].lower()
    parser = get_parser(ext)
    if parser is None:
        raise ValueError(f"不支持的文件类型: {ext}（文件: {file_path}）")
    return parser.parse(file_path)


def supported_extensions() -> list[str]:
    """返回所有已注册的文件扩展名"""
    return list(_PARSER_MAP.keys())
