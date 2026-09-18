"""Document parsers with lazy public imports.

Importing one lightweight parser must not require every optional format dependency
(for example PyMuPDF for PDF files).
"""

from parsers.base import BaseParser

__all__ = [
    "BaseParser", "DocumentParser", "HtmlParser", "PptxParser", "XlsxParser",
    "get_parser", "parse_file", "supported_extensions",
]


def __getattr__(name: str):
    if name in {"DocumentParser", "get_parser", "parse_file", "supported_extensions"}:
        from parsers import registry
        return getattr(registry, name)
    if name == "HtmlParser":
        from parsers.html_parser import HtmlParser
        return HtmlParser
    if name == "PptxParser":
        from parsers.pptx_parser import PptxParser
        return PptxParser
    if name == "XlsxParser":
        from parsers.xlsx_parser import XlsxParser
        return XlsxParser
    raise AttributeError(name)
