"""Private evidence validation, release boundaries and generation budget."""

import json
from types import SimpleNamespace

import pytest

from agent.evidence.answer_grounding import parse_grounded_answer, validate_grounded_answer
from agent.runtime.state import StopReason
from agent.service.access_guard import CURRENT_ACCESS_GUARD
from agent.streaming.live import CURRENT_STREAM_SINK
from tests.unit.test_fast_pipeline import Model, run

pytestmark = pytest.mark.no_storage


def envelope(answer="Fusion was completed July 30 [1]", quote="Fusion completed July 30"):
    return {"answer": answer, "claims": [{"text": answer, "supports": [
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
    draft.answer = draft.claims[0].text = "Fusion was completed July 30"
    assert validate_grounded_answer(draft, sources)["answer"].endswith('[2]')


def test_explicit_abstention_does_not_become_an_access_or_quality_error():
    turn, model, _ = run(model=Model('{"answer":"","claims":[]}'))
    assert turn.response.status == "no_relevant_context"
    assert not turn.response.answer and not turn.response.citations
    assert len(model.calls) == 1


def test_missing_claims_or_unbound_answer_is_rejected():
    payload = envelope()
    payload["claims"] = []
    with pytest.raises(ValueError):
        check(payload)
    payload = envelope()
    payload["answer"] = "The budget is one million."
    assert not check(payload)["valid"]


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
    payload = {"answer": "Alpha is done.\n\nBeta is active.", "claims": [
        {"text": "Alpha is done.", "supports": [{"citation_id": 1, "quote": "Alpha: done"}]},
        {"text": "Beta is active.", "supports": [{"citation_id": 2, "quote": "Beta: active"}]},
    ]}
    report = validate_grounded_answer(parse_grounded_answer(json.dumps(payload)), [
        {"content": "Alpha: done"}, {"content": "Beta: active"}])
    assert report["valid"] and report["answer"] == "Alpha is done.[1]\n\nBeta is active.[2]"
    assert check(envelope())["answer"] == "Fusion was completed July 30 [1]"


def test_independent_answer_preserves_layout_and_ignores_claim_list_order():
    payload = {"answer": "**Alpha is done.** Beta is active.", "claims": [
        {"text": "Beta is active.", "supports": [{"citation_id": 2, "quote": "Beta: active"}]},
        {"text": "Alpha is done.", "supports": [{"citation_id": 1, "quote": "Alpha: done"}]},
    ]}
    report = validate_grounded_answer(parse_grounded_answer(json.dumps(payload)), [
        {"content": "Alpha: done"}, {"content": "Beta: active"}])
    assert report["valid"]
    assert report["answer"] == "**Alpha is done.[1]** Beta is active.[2]"
    assert report["claims"][0]["model_answer_spans"] == [{"start": 19, "end": 34}]


def test_unbound_citations_still_reject_entire_answer():
    payload = envelope(answer="Fusion completed July 30.")
    payload["answer"] += " [1]"
    report = check(payload)
    assert not report["valid"] and report["answer"] == ""


def test_presentation_text_and_bullet_labels_are_not_forced_into_assertions():
    payload = envelope(answer="Fusion completed July 30.")
    payload["answer"] = "Here are the requested details:\n\n- Completion date: " + payload["answer"]
    report = check(payload)
    assert report["valid"]
    span = report["claims"][0]["model_answer_spans"][0]
    assert span["start"] == len("Here are the requested details:\n\n- Completion date: ")
    assert report["answer"].endswith("Fusion completed July 30.[1]")


def test_binding_does_not_claim_to_detect_omitted_factual_assertions():
    payload = envelope(answer="Fusion completed July 30.")
    payload["answer"] += " The budget is one million."
    report = check(payload)
    assert report["valid"]
    assert report["claim_completeness"] == "model_selected_not_verified"


def test_repeated_claim_text_binds_every_occurrence_without_reconstructing_body():
    payload = envelope(answer="Fusion completed July 30.")
    payload["answer"] += "\n\n" + payload["answer"]
    report = check(payload)
    assert report["valid"]
    assert len(report["claims"][0]["model_answer_spans"]) == 2
    assert report["answer"] == "Fusion completed July 30.[1]\n\nFusion completed July 30.[1]"


def test_overlapping_claims_are_rejected():
    payload = envelope(answer="Fusion completed July 30.")
    payload["claims"].append({"text": "July 30", "supports": payload["claims"][0]["supports"]})
    assert "claim_2:overlapping_claims" in check(payload)["errors"]


@pytest.mark.parametrize("payload", [{"claims": []}, {"answer": "Answer", "claims": []},
                                    {"answer": "", "claims": envelope()["claims"]}])
def test_answer_is_required_and_cannot_bypass_binding_as_abstention(payload):
    turn, model, _ = run(model=Model(json.dumps(payload)))
    assert turn.response.status == "quality_validation_failed"
    assert not turn.response.answer and len(model.calls) == 1


def test_unicode_capability_offsets_count_characters_in_original_body():
    payload = envelope(answer="Café completed July 30.")
    report = check(payload)
    assert report["valid"]
    span = report["claims"][0]["model_answer_spans"][0]
    assert payload["answer"][span["start"]:span["end"]] == payload["claims"][0]["text"]


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
