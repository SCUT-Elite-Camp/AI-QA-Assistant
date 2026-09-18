from confluence_pull import build_source_url, merge_metadata, normalize_confluence_base


def test_normalize_confluence_cloud_site_root() -> None:
    assert normalize_confluence_base(
        "https://example.atlassian.net/"
    ) == "https://example.atlassian.net/wiki"
    assert normalize_confluence_base(
        "https://example.atlassian.net/wiki"
    ) == "https://example.atlassian.net/wiki"


def test_build_source_url_preserves_cloud_wiki_prefix() -> None:
    assert build_source_url(
        "https://example.atlassian.net/wiki",
        "/spaces/RAG/pages/123/Page+Title",
        "123",
    ) == "https://example.atlassian.net/wiki/spaces/RAG/pages/123/Page+Title"


def test_build_source_url_accepts_wiki_and_absolute_links() -> None:
    assert build_source_url(
        "https://example.atlassian.net/wiki",
        "/wiki/spaces/RAG/pages/123/Page+Title",
        "123",
    ) == "https://example.atlassian.net/wiki/spaces/RAG/pages/123/Page+Title"
    assert build_source_url(
        "https://example.atlassian.net/wiki",
        "https://docs.example.test/page/123",
        "123",
    ) == "https://docs.example.test/page/123"


def test_build_source_url_has_safe_page_fallback() -> None:
    assert build_source_url(
        "https://example.atlassian.net/wiki/",
        None,
        "123",
    ) == "https://example.atlassian.net/wiki/pages/123"


def test_merge_metadata_replaces_only_targeted_pages() -> None:
    existing = {
        "pages": [
            {"page_id": "1", "doc_id": "old-main"},
            {"page_id": "1", "doc_id": "old-attachment"},
            {"page_id": "2", "doc_id": "untouched"},
        ]
    }
    incoming = [{"page_id": "1", "doc_id": "new-main"}]

    assert merge_metadata(existing, incoming, {"1"}) == [
        {"page_id": "2", "doc_id": "untouched"},
        {"page_id": "1", "doc_id": "new-main"},
    ]
