"""Parser package with optional format dependencies loaded on demand."""

from importlib import import_module
from typing import Any

from parsers.base import BaseParser


__all__ = [
    "BaseParser", "DocumentParser", "get_parser", "parse_file", "supported_extensions",
    "PptxParser", "HtmlParser", "XlsxParser",
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
    raise AttributeError(name)
