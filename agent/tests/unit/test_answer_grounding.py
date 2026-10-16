"""Private evidence validation, release boundaries and generation budget."""

import json
from types import SimpleNamespace

import pytest

from agent.answer.generator import AnswerGenerator
from agent.answer.schemas import AnswerCompletenessResult
from agent.evidence.answer_grounding import parse_grounded_answer, validate_grounded_answer
from agent.runtime.state import AgentState, StopReason
from agent.runtime.support import RuntimeSupport
from agent.schemas.query_plan import QueryPlan
from agent.schemas.intent_policy import IntentPolicy
from agent.service.access_guard import CURRENT_ACCESS_GUARD
from agent.streaming.live import CURRENT_STREAM_SINK
from tests.unit.test_fast_pipeline import Model, run

pytestmark = pytest.mark.no_storage


def envelope(answer="Fusion was completed July 30 [1]", quote="Fusion completed July 30"):
    return {"claims": [{"text": answer, "supports": [
        {"citation_id": 1, "quote": quote},
    ]}]}


def check(payload, source="Fusion completed July 30"):
    return validate_grounded_answer(parse_grounded_answer(json.dumps(payload)), [
        {"content": source, "doc_id": "doc", "chunk_id": "chunk", "content_hash": "hash", "source_version": "v1"},
    ])


def test_exact_excerpts_and_offsets_are_private_and_bound_to_source():
    report = check(envelope(quote="Fusion completed July 30"), "Header\nFusion  completed\nJuly 30\nFooter")
    assert report["valid"]
    fragment = report["claims"][0]["supports"][0]
    assert report["claims"][0]["claim_id"] == "claim_1"
    assert fragment["quote"] == "Fusion  completed\nJuly 30"
    assert fragment["source_start"] == 7
    assert fragment["content_hash"] == "hash" and fragment["source_version"] == "v1"


@pytest.mark.parametrize("raw", ["Plain answer [1]", '```json\n{}\n```', '{"claims":[],"claims":[]}', '[]', '{}'])
def test_unstructured_or_ambiguous_protocol_is_rejected(raw):
    with pytest.raises(ValueError):
        parse_grounded_answer(raw)


def test_fabricated_quote_rejects_all_answer_text():
    turn, model, _ = run(model=Model(json.dumps(envelope(quote="invented original text"))))
    assert turn.response.status == "quality_validation_failed"
    assert turn.result.stop_reason == StopReason.QUALITY_VALIDATION_FAILED
    assert not turn.response.answer and not turn.response.citations
    assert len(model.calls) == 1
    assert not turn.result.answer_grounding["valid"]


def test_quote_in_another_excerpt_of_same_document_does_not_validate_wrong_reference():
    draft = parse_grounded_answer(json.dumps(envelope(quote="Fusion completed July 30")))
    sources = [{"doc_id": "same", "content": "Introduction"},
               {"doc_id": "same", "content": "Fusion completed July 30"}]
    assert not validate_grounded_answer(draft, sources)["valid"]
    draft.claims[0].supports[0].citation_id = 2
    draft.claims[0].text = "Fusion was completed July 30"
    assert validate_grounded_answer(draft, sources)["answer"].endswith('[2]')


def test_explicit_abstention_does_not_become_an_access_or_quality_error():
    turn, model, _ = run(model=Model('{"claims":[]}'))
    assert turn.response.status == "no_relevant_context"
    assert not turn.response.answer and not turn.response.citations
    assert len(model.calls) == 1
    state = AgentState(trace_id="abstain", query_plan=QueryPlan(original_query="q", standalone_query="q"),
                       evidence=[{"content": "Introduction"}])
    result = RuntimeSupport.result(state, StopReason.FINAL_ANSWER, answer='{"claims":[]}')
    assert result.stop_reason == StopReason.NO_RELEVANT_CONTEXT and not result.answer


def test_missing_claims_or_a_second_unbound_answer_is_rejected():
    payload = envelope()
    payload["claims"] = []
    assert not check(payload)["valid"]
    payload = envelope()
    payload["answer"] = "The budget is one million."
    with pytest.raises(ValueError):
        check(payload)


def test_unknown_reference_or_unbound_inline_citation_is_rejected():
    payload = envelope()
    payload["claims"][0]["supports"][0]["citation_id"] = 2
    assert not check(payload)["valid"]
    payload = envelope()
    payload["claims"][0]["text"] = "A different claim [2]"
    assert not check(payload)["valid"]


def test_binding_success_is_explicitly_not_a_semantic_verdict():
    report = check(envelope(answer="Fusion completed 2023-07-30"))
    assert report["valid"] and report["semantic_validation"] == "not_performed"
    assert report["validation_kind"] == "binding"
    assert report["answer"] == "Fusion completed 2023-07-30[1]"


def test_missing_visible_citations_are_rendered_from_valid_bindings():
    report = check(envelope(answer="Fusion completed July 30."))
    assert report["valid"] and report["answer"] == "Fusion completed July 30.[1]"
    assert report["claims"][0]["model_answer_spans"] == [{"start": 0, "end": len(report["model_answer"])}]


def test_multiple_claims_render_separate_citations_without_duplicates():
    payload = {"claims": [
        {"text": "Alpha is done.", "supports": [{"citation_id": 1, "quote": "Alpha: done"}]},
        {"text": "Beta is active.", "supports": [{"citation_id": 2, "quote": "Beta: active"}]},
    ]}
    report = validate_grounded_answer(parse_grounded_answer(json.dumps(payload)), [
        {"content": "Alpha: done"}, {"content": "Beta: active"}])
    assert report["valid"] and report["answer"] == "Alpha is done.[1]\n\nBeta is active.[2]"
    assert check(envelope())["answer"] == "Fusion was completed July 30 [1]"


def test_image_region_and_text_fragment_cannot_be_interchanged():
    payload = envelope()
    support = payload["claims"][0]["supports"][0]
    support.pop("quote")
    support["image_region"] = [0.1, 0.1, 0.9, 0.9]
    draft = parse_grounded_answer(json.dumps(payload))
    assert validate_grounded_answer(draft, [{"content_kind": "file"}])["valid"]
    assert not validate_grounded_answer(draft, [{"content": "text"}])["valid"]
    support["image_region"] = [0.9, 0.1, 0.1, 0.9]
    with pytest.raises(ValueError):
        parse_grounded_answer(json.dumps(payload))


def test_fast_private_binding_without_inline_citations_is_accepted_and_not_public():
    payload = envelope(answer="Answer", quote="knowledge source text")
    turn, model, _ = run(model=Model(json.dumps(payload)))
    assert turn.response.status == "success" and turn.response.answer == "Answer[1]"
    report = turn.result.answer_grounding
    assert report["claims"][0]["supports"][0]["quote"] == "knowledge source text"
    assert set(payload["claims"][0]["supports"][0]) == {"citation_id", "quote"}
    assert '"claims"' not in turn.response.model_dump_json()
    assert len(model.calls) == 1


def test_thinking_final_fallback_cannot_skip_private_validation():
    state = AgentState(trace_id="test", query_plan=QueryPlan(original_query="q", standalone_query="q"), evidence=[{"content": "Fusion completed July 30"}])
    result = RuntimeSupport.result(state, StopReason.FINAL_ANSWER, answer="Unvalidated fallback [1]")
    assert result.stop_reason == StopReason.QUALITY_VALIDATION_FAILED and not result.answer
    result = RuntimeSupport.result(state, StopReason.FINAL_ANSWER, answer=json.dumps(envelope()))
    assert result.stop_reason == StopReason.FINAL_ANSWER and result.answer_grounding["valid"]
    state.answer_grounding_draft = envelope()
    result = RuntimeSupport.result(state, StopReason.FINAL_ANSWER, answer="Changed after validation [1]")
    assert result.stop_reason == StopReason.QUALITY_VALIDATION_FAILED and not result.answer


@pytest.mark.parametrize("valid_quote", [True, False])
def test_fast_sse_only_releases_accepted_visible_text(valid_quote):
    released = []
    guard = SimpleNamespace(check_dependencies=lambda: None, provenance=lambda: SimpleNamespace(model_dump=lambda: {}))
    guard_token = CURRENT_ACCESS_GUARD.set(guard)
    stream_token = CURRENT_STREAM_SINK.set(lambda name, payload: released.append((name, payload)))
    try:
        payload = envelope(answer="Answer", quote="knowledge source text" if valid_quote else "fabricated")
        turn, model, _ = run(model=Model(json.dumps(payload)))
    finally:
        CURRENT_STREAM_SINK.reset(stream_token)
        CURRENT_ACCESS_GUARD.reset(guard_token)
    assert (turn.response.status == "success") is valid_quote
    tokens = [data["content"] for name, data in released if name == "token"]
    assert tokens == (["Answer[1]"] if valid_quote else [])
    assert '"claims"' not in json.dumps(released) and len(model.calls) == 1


def test_thinking_generator_never_streams_private_json_or_reasoning():
    released = []
    raw = json.dumps(envelope())
    class StreamingModel:
        def stream_chat(self, *args, **kwargs):
            yield {"reasoning_content": "private claim evaluation"}
            yield {"content": raw[:20]}
            yield {"content": raw[20:]}
    guard_token = CURRENT_ACCESS_GUARD.set(SimpleNamespace(provenance=lambda: SimpleNamespace(model_dump=lambda: {})))
    stream_token = CURRENT_STREAM_SINK.set(lambda name, payload: released.append((name, payload)))
    try:
        result = AnswerGenerator(llm=StreamingModel()).chat([], grounded=True)
    finally:
        CURRENT_STREAM_SINK.reset(stream_token)
        CURRENT_ACCESS_GUARD.reset(guard_token)
    assert result["content"] == raw
    assert not any(name in {"token", "reasoning"} for name, _ in released)


@pytest.mark.parametrize("accept_repair", [True, False])
def test_thinking_repair_replaces_support_data_only_when_valid(accept_repair):
    original = envelope()
    candidate = envelope(answer=original["claims"][0]["text"] + " Extra [1]", quote="Fusion completed July 30" if accept_repair else "fabricated")
    class Checker:
        def check(self, *args):
            return AnswerCompletenessResult(complete=False, check_performed=True, missing_aspects=["Extra"])
        def repair(self, *args, grounded=False):
            assert grounded
            return parse_grounded_answer(json.dumps(candidate))
    state = AgentState(trace_id="test", query_plan=QueryPlan(original_query="q", standalone_query="q"),
        evidence=[{"doc_id": "doc", "chunk_id": "chunk", "title": "title", "content": "Fusion completed July 30", "score": 1.0,
                   "retrieval_query": "q", "retrieval_mode": "hybrid"}],
        answer_grounding_draft=original)
    support = RuntimeSupport(Checker())
    answer = support.check_and_repair_answer(state=state, policy=IntentPolicy(requires_citations=True), answer=original["claims"][0]["text"])
    assert answer == (candidate["claims"][0]["text"] if accept_repair else original["claims"][0]["text"])
    result = support.result(state, StopReason.FINAL_ANSWER, answer=answer)
    assert result.stop_reason == StopReason.FINAL_ANSWER and result.answer_grounding["valid"]
