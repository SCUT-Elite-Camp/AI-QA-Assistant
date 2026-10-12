"""Parser package with optional format dependencies loaded on demand."""

from importlib import import_module
from typing import Any

from parsers.base import BaseParser


__all__ = [
    "BaseParser", "DocumentParser", "get_parser", "parse_file", "supported_extensions",
    "PptxParser", "HtmlParser", "XlsxParser",
    "CamelotTableBackend", "GMFTTableBackend", "PaddleOCRTableBackend",
    "PyMuPDFTableBackend", "TableBackend", "TableQualityEvidence",
    "TableQualityScorer", "TableRouter", "TableRouterConfig",
]


def __getattr__(name: str) -> Any:
    if name in {"DocumentParser", "get_parser", "parse_file", "supported_extensions"}:
        return getattr(import_module("parsers.registry"), name)
    modules = {
        "PptxParser": "parsers.pptx_parser",
        "HtmlParser": "parsers.html_parser",
        "XlsxParser": "parsers.xlsx_parser",
    }
    if name in modules:
        return getattr(import_module(modules[name]), name)
    table_modules = {
        "CamelotTableBackend": "parsers.table_backends",
        "GMFTTableBackend": "parsers.table_backends",
        "PaddleOCRTableBackend": "parsers.table_backends",
        "PyMuPDFTableBackend": "parsers.table_backends",
        "TableBackend": "parsers.table_router",
        "TableQualityEvidence": "parsers.table_router",
        "TableQualityScorer": "parsers.table_router",
        "TableRouter": "parsers.table_router",
        "TableRouterConfig": "parsers.table_router",
    }
    if name in table_modules:
        return getattr(import_module(table_modules[name]), name)
    raise AttributeError(name)
