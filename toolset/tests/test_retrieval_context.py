from retrieval.context import attach_context


def row(chunk_id, **changes):
    return dict(doc_id='allowed', version_id='v1', chunk_id=chunk_id,
                chunk_text='Original source text', score=.7, read_status='original_excerpt_loaded',
                locator={'section_path':['Design']}, **changes)


def test_neighbors_keep_independent_hashes_and_do_not_replace_primary_hits():
    first = row('one');first['locator']['next_chunk_id'] = 'two'
    next_row = row('two', content_hash='body-hash', evidence_ref='separate-reference')
    result = attach_context([first], lambda parent, key: next_row)
    assert result[0]['chunk_id'] == 'one'
    assert result[0]['context_chunks'][0]['evidence_ref'] == 'separate-reference'
    assert result[0]['context_chunks'][0]['content_hash'] == 'body-hash'
    assert 'context_chunks' not in first


def test_neighbor_cannot_cross_source_version_or_section():
    first = row('one');first['locator']['next_chunk_id'] = 'two'
    for changes in [{'doc_id':'denied'}, {'version_id':'v2'}, {'locator':{'section_path':['Other']}},
                    {'read_status':'retrieval_hit'}, {'chunk_text':'x'*2001}]:
        neighbor = row('two');neighbor.update(changes)
        assert 'context_chunks' not in attach_context([first], lambda parent, key: neighbor)[0]
