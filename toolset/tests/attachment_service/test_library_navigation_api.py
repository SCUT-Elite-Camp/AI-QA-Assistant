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
        return [{
            "id": "sec-1", "attachment_id": "ver-1", "title": "Retention",
            "parent_id": "sec-root", "quality": "high", "level": 1,
            "evidence_ids": ["ev-section"],
        }]

    def list_sections(self, attachment_ids):
        return [
            {
                "id": "sec-root", "attachment_id": "ver-1", "title": "Policy",
                "quality": "high", "level": 0, "ordinal": 0,
                "evidence_ids": ["ev-direct", "ev-section"],
            },
            {
                "id": "sec-1", "attachment_id": "ver-1", "title": "Retention",
                "parent_id": "sec-root", "quality": "high", "level": 1,
                "ordinal": 1, "evidence_ids": ["ev-section"],
            },
        ]


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


def test_enabled_hierarchical_flag_still_requires_explicit_exploration(app_module, monkeypatch):
    store = _Store()
    monkeypatch.setattr(app_module, "STORE", store)
    monkeypatch.setattr(
        app_module, "SETTINGS", SimpleNamespace(hierarchical_navigation_enabled=True),
    )

    result = app_module.search_library(_request(app_module))

    assert result["navigation"]["mode"] == "direct"
    assert result["navigation"]["requested_mode"] == "hierarchical"
    assert result["navigation"]["fallback_reason"] == "explicit_exploration_only"
    assert result["navigation"]["section_hits"] == 0
    assert store.section_searches == 0
    assert result["items"][0]["evidence_id"] == "ev-direct"
    assert all(item["version_id"] == "ver-1" for item in result["items"])


def test_personal_outline_is_navigation_metadata_only(app_module, monkeypatch):
    store = _Store()
    monkeypatch.setattr(app_module, "STORE", store)

    result = app_module.browse_library_outline(app_module.LibraryOutlineRequest(
        owner_id="user-1", knowledge_base_id="kb-1", query="retention", top_k=5,
    ))

    assert result["citation_authority"] is False
    assert result["sections"][0]["id"] == "sec-1"
    assert result["sections"][0]["navigation_relation"] == "matched"
    assert result["sections"][1]["id"] == "sec-root"
    assert result["sections"][1]["navigation_relation"] == "ancestor"


def test_personal_scoped_search_rejects_unknown_section_and_returns_authoritative_evidence(
    app_module, monkeypatch,
):
    store = _Store()
    monkeypatch.setattr(app_module, "STORE", store)
    authorized = app_module.search_library_scoped(app_module.LibraryScopedSearchRequest(
        owner_id="user-1", knowledge_base_id="kb-1", query="retention",
        section_ids=["sec-1"], mode="bm25", top_k=5,
    ))
    denied = app_module.search_library_scoped(app_module.LibraryScopedSearchRequest(
        owner_id="user-1", knowledge_base_id="kb-1", query="retention",
        section_ids=["sec-other"], mode="bm25", top_k=5,
    ))

    assert authorized["citation_authority"] is True
    assert authorized["items"][0]["evidence_id"] == "ev-section"
    assert authorized["items"][0]["matched_section_ids"] == ["sec-1"]
    assert denied["items"] == []
