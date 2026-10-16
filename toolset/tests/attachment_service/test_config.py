from __future__ import annotations

import base64
from pathlib import Path

import pytest

from data_persistence.file_settings import AttachmentSettings


def _required_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", "test-secret")
    monkeypatch.setenv(
        "ATTACHMENT_ENCRYPTION_KEY",
        base64.urlsafe_b64encode(b"k" * 32).decode(),
    )


def test_production_parser_needs_no_scanner_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    _required_environment(monkeypatch)
    monkeypatch.setenv("NODE_ENV", "production")
    settings = AttachmentSettings.from_env()
    assert settings.internal_secret == "test-secret"


def test_relocated_settings_keep_the_existing_attachment_directory(monkeypatch):
    _required_environment(monkeypatch)
    monkeypatch.delenv("ATTACHMENT_DATA_DIR", raising=False)
    repository = Path(__file__).resolve().parents[3]
    assert AttachmentSettings.from_env().data_dir == repository / "data-persistence" / "data" / "attachments"
