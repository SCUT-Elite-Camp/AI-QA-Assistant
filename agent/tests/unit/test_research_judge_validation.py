import pytest
import json
from eval import research_product_acceptance as runner
from eval.research_product_acceptance import validate_judge_result


def test_native_rendered_chunk_is_valid_even_when_source_has_comments():
    case = dict(allowed_document_ids=['d'], key_source_locations=[], judge_sources=[dict(
        doc_id='d', content='# Goals\n<!-- source local id -->\n| Goal | Status |',
        chunks=[dict(chunk_id='d_0', text='# Goals\n| Goal | Status |')])])
    result = runner.source_metrics(case, dict(citations=[dict(doc_id='d', chunk_id='d_0',
        snippet='# Goals\n| Goal | Status |')]))
    assert result['locator_excerpt_valid_rate'] == 1


def test_context_is_bound_to_its_actual_anchor_not_another_chunk():
    case = dict(allowed_document_ids=['d'], key_source_locations=[], judge_sources=[dict(
        doc_id='d', content='first\n<!-- native comment -->\nsecond', chunks=[
            dict(chunk_id='d_0', index=0, text='first'), dict(chunk_id='d_1', index=1, text='second')])])
    result = runner.source_metrics(case, dict(citations=[dict(doc_id='d', chunk_id='d_1',
        excerpt='first\n\nsecond', anchor_excerpt='second')]))
    assert result['locator_excerpt_valid_rate'] == 1
    result = runner.source_metrics(case, dict(citations=[dict(doc_id='d', chunk_id='d_1', snippet='first')]))
    assert result['locator_excerpt_valid_rate'] == 0


def test_reader_overlap_removal_remains_source_bound():
    case = dict(allowed_document_ids=['d'], key_source_locations=[], judge_sources=[dict(
        doc_id='d', content='Original with comments', chunks=[
            dict(chunk_id='d_0', index=0, text='first shared tail'),
            dict(chunk_id='d_1', index=1, text='shared tail second')])])
    row = dict(doc_id='d', chunk_id='d_1', excerpt='first shared tail second', anchor_excerpt='shared tail second')
    assert runner.source_metrics(case, dict(citations=[row]))['locator_excerpt_valid_rate'] == 1
    row['excerpt'] += ' invented addition'
    assert runner.source_metrics(case, dict(citations=[row]))['locator_excerpt_valid_rate'] == 0


@pytest.mark.parametrize('value,error', [
    (7, 'invalid_judge_object'),
    ({'checks_passed': [True]}, 'invalid_judge_score'),
    ({'checks_passed': [False], 'faithfulness': 5, 'citation_support': 5,
      'rationale': 'check 1 passes: true'}, 'inconsistent_judge_rationale'),
])
def test_invalid_verdict(value, error):
    with pytest.raises(ValueError, match=error):
        validate_judge_result(value, 1)


def test_valid_negative_is_not_changed():
    result = dict(checks_passed=[False], faithfulness=2, citation_support=2,
                  rationale='Unsupported claim.')
    validate_judge_result(result, 1)
    assert result['checks_passed'] == [False]


@pytest.mark.parametrize('values', [[7, True], [False], [7, 7]])
def test_bounded_retry_preserves_raw_verdicts(monkeypatch, values):
    for key, value in {'LLM_MODEL': 'fake', 'LLM_API_BASE': 'https://example.invalid',
                       'LLM_API_KEY': 'fake'}.items():
        monkeypatch.setenv(key, value)
    calls = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            value = values[len(calls) - 1]
            verdict = value if type(value) is int else dict(
                checks_passed=[value], faithfulness=5, citation_support=5, rationale='Reviewed.')
            return json.dumps({'choices': [{'message': {'content': json.dumps(verdict)}}]}).encode()

    def transport(request, **kwargs):
        calls.append(request)
        return Response()

    monkeypatch.setattr(runner, 'urlopen', transport)
    case = dict(question='Question', checks=['Check'], judge_sources=[])
    if values == [7, 7]:
        with pytest.raises(runner.JudgeValidationError) as caught:
            runner.judge(case, 'Unchanged answer', [])
        assert len(caught.value.attempts) == 2
        assert caught.value.attempts[0]['raw_content'] == '7'
    else:
        result = runner.judge(case, 'Unchanged answer', [])
        assert result['checks_passed'] == [values[-1]]
        assert len(result['validation_attempts']) == len(values)
    assert len(calls) == len(values)


def test_qwen_json_judge_disables_provider_thinking(monkeypatch):
    monkeypatch.setenv('LLM_MODEL', 'qwen3-30b-a3b')
    monkeypatch.setenv('LLM_API_BASE', 'https://example.invalid')
    monkeypatch.setenv('LLM_API_KEY', 'fake')
    monkeypatch.setenv('LLM_THINKING_MODE', 'enabled')
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            return json.dumps({'choices': [{'message': {'content': json.dumps(dict(
                checks_passed=[True, True], faithfulness=5, citation_support=5,
                rationale='Both supported.'))}}]}).encode()
    def transport(request, **kwargs):
        payload = json.loads(request.data)
        assert payload['enable_thinking'] is False
        assert 'thinking' not in payload
        assert len(json.loads(payload['messages'][-1]['content'].split(': ', 1)[1])['checks_passed']) == 2
        return Response()
    monkeypatch.setattr(runner, 'urlopen', transport)
    result = runner.judge(dict(question='Q', checks=['A', 'B'], judge_sources=[]), 'Answer', [])
    assert result['request_options']['enable_thinking'] is False


def test_provider_failure_keeps_code_without_retry_or_secret_message(monkeypatch):
    from io import BytesIO
    from urllib.error import HTTPError
    for key, value in {'LLM_MODEL': 'fake', 'LLM_API_BASE': 'https://example.invalid',
                       'LLM_API_KEY': 'fake'}.items():
        monkeypatch.setenv(key, value)
    calls = []
    def transport(request, **kwargs):
        calls.append(request)
        raise HTTPError(request.full_url, 403, 'Forbidden', {}, BytesIO(json.dumps({
            'error': {'code': 'insufficient_quota', 'message': 'private-secret'}}).encode()))
    monkeypatch.setattr(runner, 'urlopen', transport)
    with pytest.raises(runner.JudgeProviderError) as caught:
        runner.judge(dict(question='Q', checks=['A'], judge_sources=[]), 'Answer', [])
    assert 'insufficient_quota' in str(caught.value)
    assert 'private-secret' not in str(caught.value)
    assert len(calls) == 1
