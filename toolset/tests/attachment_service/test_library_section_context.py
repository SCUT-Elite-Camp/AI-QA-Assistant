from attachment_service.library_service import resolve_section_search_context


def test_explicit_document_title_becomes_filter_not_section_rank_signal():
    versions = [
        {"id": "version-a", "filename": "Alpha Research Paper.md"},
        {"id": "version-b", "filename": "Beta Study.pdf"},
    ]

    attachment_ids, section_query = resolve_section_search_context(
        'In the paper "Alpha Research Paper", which dataset was used?', versions,
    )

    assert attachment_ids == ["version-a"]
    assert "Alpha Research Paper" not in section_query
    assert "which dataset was used?" in section_query


def test_section_context_keeps_authorized_scope_when_no_title_matches():
    versions = [
        {"id": "version-a", "filename": "Alpha Research Paper.md"},
        {"id": "version-b", "filename": "Beta Study.pdf"},
    ]

    attachment_ids, section_query = resolve_section_search_context(
        "Which dataset was used?", versions,
    )

    assert attachment_ids == ["version-a", "version-b"]
    assert section_query == "Which dataset was used?"
