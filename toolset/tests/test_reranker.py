import pytest
from retrieval.reranker import rerank
from tool_layer.search_tool import SearchTool


def test_ranking_preserves_evidence_and_retrieval_scores(monkeypatch):
    monkeypatch.setenv('RERANK_ENABLED', 'true')
    rows = [{'doc_id': 'allowed', 'chunk_text': 'Introduction', 'score': .9},
            {'doc_id': 'allowed', 'chunk_text': 'The eight stop conditions', 'score': .4}]
    result = rerank('List stop conditions', rows, 1, predictor=lambda pairs: [-2, 5])
    assert result[0]['chunk_text'] == rows[1]['chunk_text']
    assert result[0]['score'] == .4 and result[0]['rerank_score'] == 5
    assert result[0]['retrieval_rank'] == 2
    assert 'rerank_score' not in rows[1]


def test_duplicate_suppression_keeps_distinct_source_provenance(monkeypatch):
    monkeypatch.setenv('RERANK_ENABLED', 'true')
    rows = [{'doc_id': 'one', 'version_id': 'v1', 'chunk_text': 'Same', 'score': .8},
            {'doc_id': 'one', 'version_id': 'v1', 'chunk_text': 'Same', 'score': .7},
            {'doc_id': 'two', 'version_id': 'v1', 'chunk_text': 'Same', 'score': .6}]
    result = rerank('Question', rows, 5, predictor=lambda pairs: [2, 1])
    assert [r['doc_id'] for r in result] == ['one', 'two']


def test_invalid_scores_are_visible_degradation(monkeypatch):
    monkeypatch.setenv('RERANK_ENABLED', 'true')
    rows = [{'doc_id': 'one', 'chunk_text': 'Original', 'score': .8}]
    result = rerank('Question', rows, 5, predictor=lambda pairs: [float('nan')])
    assert result[0]['rerank_status'] == 'degraded'
    assert result[0]['chunk_text'] == 'Original'


def test_tool_normalizes_scope_before_model_and_requests_twenty(monkeypatch, tmp_path):
    import json
    monkeypatch.setenv('RERANK_ENABLED', 'true')
    class Backend:
        def search(self, query, top_k, mode, filters):
            assert top_k == 20
            return [{'doc_id': name, 'chunk_index': 0, 'chunk_text': name, 'score': 1}
                    for name in ['allowed', 'denied']]
    seen = []
    (tmp_path/'allowed.json').write_text(json.dumps({'doc_id':'allowed','content':'allowed',
        'chunks':[{'index':0,'chunk_id':'allowed_chunk_0','text':'allowed'}]}), encoding='utf-8')
    def rank(query, rows, top_k):
        seen.extend(rows)
        return rows[:top_k]
    monkeypatch.setattr('tool_layer.search_tool.rerank', rank)
    result = SearchTool(backend=Backend(), documents_dir=str(tmp_path)).search_direct(
        'Question', filters={'doc_ids': ['allowed']})
    assert [r['doc_id'] for r in seen] == ['allowed']
    assert [r['doc_id'] for r in result] == ['allowed']


def test_stale_text_is_not_sent_to_the_reranker(monkeypatch, tmp_path):
    import json
    monkeypatch.setenv('RERANK_ENABLED', 'true')
    (tmp_path/'doc.json').write_text(json.dumps({'doc_id':'doc','content':'Current',
        'chunks':[{'index':0,'chunk_id':'doc_chunk_0','text':'Current'}]}), encoding='utf-8')
    class Backend:
        def search(self, *args, **kwargs):
            return [{'doc_id':'doc','chunk_index':0,'chunk_text':'Stale','score':1}]
    monkeypatch.setattr('tool_layer.search_tool.rerank', lambda q, rows, k: rows)
    assert SearchTool(backend=Backend(), documents_dir=str(tmp_path)).search_direct('Question') == []


def test_mixed_source_pool_preserves_original_objects_and_lineage(monkeypatch):
    from types import SimpleNamespace
    from retrieval.evidence_ranking import rank_evidence
    monkeypatch.setenv('RERANK_ENABLED', 'true')
    one = SimpleNamespace(source_type='knowledge', doc_id='same', version_id='v1',
        content='Enterprise fact', title='Enterprise', score=.8, content_hash='hash-one')
    two = SimpleNamespace(source_type='personal', doc_id='same', version_id='v2',
        content='Private fact', title='Personal', score=.9, content_hash='hash-two')
    def rank(query, rows, top_k):
        assert {r['doc_id'] for r in rows} == {'knowledge:same', 'personal:same'}
        return list(reversed(rows))[:top_k]
    monkeypatch.setattr('retrieval.evidence_ranking.rerank', rank)
    result = rank_evidence('Question', [one, two], 2)
    assert result == [two, one]
    assert result[0] is two and result[0].content_hash == 'hash-two'


def test_authorization_failure_is_never_converted_to_fallback(monkeypatch):
    from retrieval.reranker import BEFORE_RERANK
    monkeypatch.setenv('RERANK_ENABLED', 'true')
    def deny(rows):raise PermissionError('revoked')
    token = BEFORE_RERANK.set(deny)
    try:
        with pytest.raises(PermissionError, match='revoked'):
            rerank('Question', [{'doc_id':'denied','chunk_text':'Secret','score':1}], 5,
                   predictor=lambda pairs: pytest.fail('model must not see denied text'))
    finally:
        BEFORE_RERANK.reset(token)


def test_identical_values_in_different_rows_or_sections_remain_separate(monkeypatch):
    monkeypatch.setenv('RERANK_ENABLED', 'true')
    rows = [{'doc_id':'report','version_id':'v1','chunk_text':'Revenue: 100','score':.9,
             'section_path':['2025'],'locator':{'row_start':1,'row_end':1}},
            {'doc_id':'report','version_id':'v1','chunk_text':'Revenue: 100','score':.8,
             'section_path':['2026'],'locator':{'row_start':2,'row_end':2}}]
    result = rerank('What is the revenue in 2026?', rows, 2, predictor=lambda pairs:[-1,4])
    assert [r['section_path'] for r in result] == [['2026'],['2025']]


def test_private_ranking_sees_only_active_owner_evidence_with_version_metadata(monkeypatch):
    from tool_layer.search_library_tool import search_library_evidence
    from retrieval.reranker import BEFORE_RERANK
    monkeypatch.setenv('RERANK_ENABLED','true')
    class Store:
        def list_library_versions(self, owner, kb, **kwargs):
            assert (owner,kb)==('owner','kb') and kwargs['active_only']
            return [{'id':'active-own','knowledge_base_id':'kb','document_id':'doc',
                     'version_id':'v1','filename':'Owned report'}]
        def search_evidence(self, ids, query, top_k):
            assert ids==['active-own'] and top_k==20
            return [{'evidence_id':'own'},{'evidence_id':'denied'}]
        def list_evidence(self, ids):
            assert ids==['active-own']
            return [{'attachment_id':'active-own','evidence_id':'own','content':'Allowed answer',
                     'read_status':'original_excerpt_loaded','content_hash':'source-hash','locator':{}}]
    observed=[]
    class Model:
        def tokenizer(self, *args, **kwargs):return {'input_ids':[1]}
        def predict(self, pairs, **kwargs):
            observed.extend(pairs)
            return [5]
    monkeypatch.setattr('retrieval.reranker._load_model',lambda *args:Model())
    def check(rows):
        assert len(rows)==1 and rows[0]['evidence_id']=='own'
        assert rows[0]['version_id']=='v1' and rows[0]['document_id']=='doc'
        assert rows[0]['source_scope']=='personal'
    token=BEFORE_RERANK.set(check)
    try:
        result=search_library_evidence({'owner_id':'owner','knowledge_base_id':'kb','query':'Question',
                                        'top_k':5,'mode':'bm25'},store=Store())
    finally:
        BEFORE_RERANK.reset(token)
    assert len(observed)==1 and 'Allowed answer' in observed[0][1]
    assert [r['evidence_id'] for r in result['items']]==['own']
    assert result['items'][0]['rerank_status']=='completed'
