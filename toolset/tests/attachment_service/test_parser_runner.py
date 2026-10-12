from pathlib import Path

import pytest


def test_parser_runner_returns_text_evidence(tmp_path: Path) -> None:
    from attachment_service.parser_runner import parse_with_timeout

    source = tmp_path / "input.txt"
    source.write_text("错误码 DB-1042", encoding="utf-8")
    items = parse_with_timeout(source, "att_runner", ".txt", 10)
    assert items[0]["content"] == "错误码 DB-1042"


def test_parser_runner_reports_child_failure(tmp_path: Path) -> None:
    from attachment_service.parser_runner import parse_with_timeout

    source = tmp_path / "input.unknown"
    source.write_bytes(b"unsupported")
    with pytest.raises(RuntimeError):
        parse_with_timeout(source, "att_runner_bad", ".unknown", 10)
