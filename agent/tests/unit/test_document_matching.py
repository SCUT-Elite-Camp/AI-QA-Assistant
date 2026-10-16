from tool_layer.document_matching import named_document_ids


def test_compound_filename_keeps_company_and_year_constraints():
    documents = [
        {'doc_id': 'current', 'title': '[Reports] AMERICANEXPRESS_2022_10K'},
        {'doc_id': 'older', 'title': '[Reports] AMERICANEXPRESS_2021_10K'},
        {'doc_id': 'other', 'title': '[Reports] JPMORGAN_2022_10K'},
    ]
    assert named_document_ids('American Express 2022年10-K披露了什么？', documents) == ['current']
    assert named_document_ids('American Express 2023年10-K披露了什么？', documents) == []


def test_literal_multilingual_match_only_uses_supplied_documents():
    assert named_document_ids('模块演进方案有哪些阶段？', [
        {'doc_id': 'allowed', 'title': '模块演进方案'},
        {'doc_id': 'unrelated', 'title': '模型选型'},
    ]) == ['allowed']
    assert named_document_ids('American Express 2022年10-K', []) == []


def test_catalog_ordinal_is_optional_but_source_year_is_required():
    documents=[{'doc_id':'api','title':'04 API Reference'},
               {'doc_id':'older','title':'2025 API Reference'}]
    assert named_document_ids('According to API Reference, what is the saved citation endpoint?',documents)==['api']
    assert named_document_ids('2025 API Reference endpoint?',documents)==['older']
