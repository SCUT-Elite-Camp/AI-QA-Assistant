"""Accepted display bindings across final citation normalization."""
import json

import pytest

from agent.evidence.answer_annotations import answer_annotations
from agent.evidence.answer_grounding import parse_grounded_answer, validate_grounded_answer
from agent.schemas.chat import Citation
from agent.streaming.sse import chat_response_events
from agent.schemas.chat import ChatResponse

pytestmark = pytest.mark.no_storage


def binding(answer="Alpha is done. Beta is active."):
    evidence = [{"content": "Alpha: done", "doc_id": "a", "chunk_id": "a1", "evidence_ref": "ev-a",
                 "content_hash": "hash-a", "source_version": "1"},
                {"content": "Beta: active", "doc_id": "b", "chunk_id": "b1", "evidence_ref": "ev-b",
                 "content_hash": "hash-b", "source_version": "2"}]
    draft = parse_grounded_answer(json.dumps({"answer": answer, "claims": [
        {"text": "Alpha is done.", "supports": [{"citation_id": 1, "quote": "Alpha: done"}]},
        {"text": "Beta is active.", "supports": [{"citation_id": 2, "quote": "Beta: active"}]},
    ]}))
    report = validate_grounded_answer(draft, evidence)
    citations = [Citation(citation_id=2-index, title=item["doc_id"], **{k: v for k, v in item.items() if k != "content"})
                 for index, item in enumerate(evidence)]
    return report, citations


def test_display_spans_use_final_body_and_source_identity_after_citation_renumbering():
    report, citations = binding()
    final = "Alpha is done.[2] Beta is active.[1]"
    annotations = answer_annotations(report, final, citations)
    assert [item.supports[0].citation_id for item in annotations] == [2, 1]
    for item in annotations:
        assert final[item.start:item.end] == item.text
    assert annotations[1].start == len("Alpha is done.[2] ")
    assert set(annotations[0].model_dump()) == {"claim_id", "text", "start", "end", "supports"}
    assert annotations[0].supports[0].quote == "Alpha: done"


def test_changed_body_or_unmatched_source_never_reuses_old_binding():
    report, citations = binding()
    assert not answer_annotations(report, "Alpha is wrong. Beta is active.", citations)
    citations[0].content_hash = "changed"
    assert not answer_annotations(report, report["answer"], citations)
    report["valid"] = False
    assert not answer_annotations(report, report["answer"], citations)


def test_unicode_capability_uses_character_offsets_including_non_bmp_prefix():
    report, citations = binding("😀 Alpha is done. Beta is active.")
    # Emoji is included in a valid whole-body claim in actual generation; here
    # exercise the projection independently of the validator's coverage policy.
    report["valid"] = True
    annotations = answer_annotations(report, report["model_answer"], citations)
    assert annotations[0].start == 2


def test_only_accepted_projection_is_streamed_never_private_verdicts():
    report, citations = binding()
    response = ChatResponse(trace_id="test", status="success", answer=report["answer"], message="", citations=citations,
                            answer_claims=answer_annotations(report, report["answer"], citations))
    event = next(value for name, value in chat_response_events(response) if name == "answer-claims")
    assert event[0]["supports"][0]["quote"] == "Alpha: done"
    assert "semantic_validation" not in json.dumps(event)
    response.status = "quality_validation_failed"
    assert all(name != "answer-claims" for name, _ in chat_response_events(response))
