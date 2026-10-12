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


def test_production_parser_needs_no_scanner_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    _required_environment(monkeypatch)
    monkeypatch.setenv("NODE_ENV", "production")
    settings = AttachmentSettings.from_env()
    assert settings.internal_secret == "test-secret"


def test_hierarchical_navigation_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    _required_environment(monkeypatch)
    monkeypatch.delenv("HIERARCHICAL_NAVIGATION_ENABLED", raising=False)
    assert AttachmentSettings.from_env().hierarchical_navigation_enabled is False
    monkeypatch.setenv("HIERARCHICAL_NAVIGATION_ENABLED", "true")
    assert AttachmentSettings.from_env().hierarchical_navigation_enabled is True
