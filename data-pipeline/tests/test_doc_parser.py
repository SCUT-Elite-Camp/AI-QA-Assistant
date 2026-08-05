import os
import tempfile
from parsers.doc_parser import DocParser
from parsers.registry import supported_extensions, parse_file


def test_doc_parser_supported_extensions() -> None:
    parser = DocParser()
    assert ".doc" in parser.supported_extensions()
    assert ".doc" in supported_extensions()


def test_doc_parser_fallback_parsing() -> None:
    with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as f:
        # Write dummy text content simulating a text-based doc fallback
        f.write("这是测试文档标题\n这是第一段测试内容。\n这是第二段测试内容。".encode("gbk"))
        f_path = f.name

    try:
        doc = parse_file(f_path)
        assert doc is not None
        assert doc.doc_id is not None
        assert "测试内容" in doc.content or "测试文档标题" in doc.content
        assert len(doc.content_blocks) >= 1
    finally:
        if os.path.exists(f_path):
            os.remove(f_path)
