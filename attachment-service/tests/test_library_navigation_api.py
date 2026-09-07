import base64
import importlib
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture()
def app_module(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", "test-secret")
    monkeypatch.setenv(
        "ATTACHMENT_ENCRYPTION_KEY",
        base64.urlsafe_b64encode(b"k" * 32).decode(),
    )
    monkeypatch.setenv("ATTACHMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ATTACHMENT_VECTOR_INDEX_ENABLED", "false")
    sys.modules.pop("attachment_service.app", None)
    module = importlib.import_module("attachment_service.app")
    yield module
    sys.modules.pop("attachment_service.app", None)


class _Store:
    def __init__(self) -> None:
        self.section_searches = 0

    def list_library_versions(self, owner_id, knowledge_base_id, **kwargs):
        return [{
            "id": "ver-1", "vector_ref": "ver-1", "knowledge_base_id": knowledge_base_id,
            "document_id": "doc-1", "version_id": "ver-1", "filename": "policy.md",
        }]

    def list_evidence(self, attachment_ids):
        return [
            {"evidence_id": "ev-direct", "attachment_id": "ver-1", "content": "general policy", "locator": {}},
            {"evidence_id": "ev-section", "attachment_id": "ver-1", "content": "retention policy", "locator": {}},
        ]

    def search_evidence(self, attachment_ids, query, top_k, evidence_ids=None):
        if evidence_ids is not None:
            return [{"evidence_id": value} for value in evidence_ids]
        return [{"evidence_id": "ev-direct"}, {"evidence_id": "ev-section"}]

    def search_sections(self, attachment_ids, query, top_k):
        self.section_searches += 1
        return [{"quality": "high", "level": 1, "evidence_ids": ["ev-section"]}]


def _request(app_module):
    return app_module.LibrarySearchRequest(
        owner_id="user-1", knowledge_base_id="kb-1", query="retention",
        mode="bm25", navigation_mode="hierarchical", top_k=2,
    )


def test_disabled_flag_forces_direct_navigation(app_module, monkeypatch):
    store = _Store()
    monkeypatch.setattr(app_module, "STORE", store)
    monkeypatch.setattr(
        app_module, "SETTINGS", SimpleNamespace(hierarchical_navigation_enabled=False),
    )

    result = app_module.search_library(_request(app_module))

    assert result["navigation"]["mode"] == "direct"
    assert result["navigation"]["requested_mode"] == "hierarchical"
    assert store.section_searches == 0


def test_enabled_hierarchical_navigation_keeps_evidence_authoritative(app_module, monkeypatch):
    store = _Store()
    monkeypatch.setattr(app_module, "STORE", store)
    monkeypatch.setattr(
        app_module, "SETTINGS", SimpleNamespace(hierarchical_navigation_enabled=True),
    )

    result = app_module.search_library(_request(app_module))

    assert result["navigation"]["mode"] == "hierarchical"
    assert result["navigation"]["section_hits"] == 1
    assert result["items"][0]["evidence_id"] == "ev-section"
    assert all(item["version_id"] == "ver-1" for item in result["items"])
