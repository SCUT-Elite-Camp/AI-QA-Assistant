from __future__ import annotations

from pipeline.wiki.search import WikiSearchBackend


class Provider:
    def __init__(self, page_ids):
        self.page_ids = page_ids
        self.calls = []

    def search(self, query, **kwargs):
        self.calls.append((query, kwargs))
        return [{"page_id": page_id, "title": page_id} for page_id in self.page_ids]


def test_wiki_search_rrf_fuses_navigation_candidates_with_scope_passthrough() -> None:
    sparse = Provider(["a", "b"])
    vector = Provider(["b", "c"])
    result = WikiSearchBackend(sparse, vector).search(
        "agent layer", source_scope="personal", owner_id="owner",
        knowledge_base_id="kb", top_k=3,
    )
    assert [item["page_id"] for item in result] == ["b", "a", "c"]
    assert all(item["citation_authority"] is False for item in result)
    assert all(call[1]["owner_id"] == "owner" for call in [*sparse.calls, *vector.calls])


def test_wiki_search_can_run_sparse_only_and_rejects_empty_query() -> None:
    sparse = Provider(["a"])
    backend = WikiSearchBackend(sparse)
    assert backend.search(
        "", source_scope="enterprise", owner_id="", knowledge_base_id="kb",
    ) == []
    result = backend.search(
        "rag", source_scope="enterprise", owner_id="", knowledge_base_id="kb",
    )
    assert [item["page_id"] for item in result] == ["a"]
