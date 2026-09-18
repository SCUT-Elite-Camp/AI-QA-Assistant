from __future__ import annotations

import base64

import pytest

from attachment_service.config import AttachmentSettings


def _required_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", "test-secret")
    monkeypatch.setenv(
        "ATTACHMENT_ENCRYPTION_KEY",
        base64.urlsafe_b64encode(b"k" * 32).decode(),
    )


def test_fake_scanner_is_forbidden_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    _required_environment(monkeypatch)
    monkeypatch.setenv("NODE_ENV", "production")
    monkeypatch.setenv("ALLOW_FAKE_ATTACHMENT_SCANNER", "true")
    with pytest.raises(RuntimeError, match="forbidden in production"):
        AttachmentSettings.from_env()


def test_fake_scanner_remains_available_for_explicit_development_testing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _required_environment(monkeypatch)
    monkeypatch.setenv("NODE_ENV", "development")
    monkeypatch.setenv("ALLOW_FAKE_ATTACHMENT_SCANNER", "true")
    assert AttachmentSettings.from_env().allow_fake_scanner is True
