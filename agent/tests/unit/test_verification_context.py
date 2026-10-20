"""English contracts for source-bound MiniCheck input construction."""
from copy import deepcopy
from dataclasses import asdict
import hashlib

import pytest

from agent.evidence.answer_grounding import GroundedAnswer, validate_grounded_answer
from agent.evidence.verification_context import build_verification_inputs

pytestmark = pytest.mark.no_storage


def source(content, *, doc="policy", chunk="section", **extra):
    return {"doc_id":doc, "chunk_id":chunk, "source_type":"knowledge", "source_scope":"enterprise",
            "evidence_ref":f"{doc}:{chunk}", "content_hash":"original-body-hash", "source_version":"7",
            "content":content, **extra}


def binding(evidence, quotes, text="The project document deadline is three days."):
    draft = GroundedAnswer.model_validate({"answer":text,"claims":[{"text":text, "supports":[
        {"citation_id":citation, "quote":quote} for citation, quote in quotes
    ]}]})
    report = validate_grounded_answer(draft, evidence)
    assert report["valid"]
    return report


def prepare(text, quote, **kwargs):
    evidence = [source(text)]
    return build_verification_inputs(binding(evidence, [(1, quote)]), evidence, **kwargs)[0]


def assert_original_spans(prepared, evidence):
    for context in prepared.sources:
        original = evidence[context.citation_id - 1]["content"]
        for span in (*context.anchors, *context.spans):
            assert original[span.start:span.end] == span.text
        assert context.excerpt_sha256 == hashlib.sha256(original.encode()).hexdigest()


def test_complete_prose_scope_keeps_later_negation_and_separate_paragraph_condition():
    text = "# Deployment in 2026\n\nAgent health proves liveness only; ready reports resource readiness.\n\nA health response does not establish retrieval readiness.\n\n## Unrelated storage\n\nBackups run nightly."
    evidence = [source(text)]
    report = binding(evidence, [(1, "health proves liveness")], text="Health proves retrieval readiness.")
    prepared = build_verification_inputs(report, evidence)[0]
    assert prepared.status == "ready"
    assert "liveness only; ready" in prepared.premise
    assert "does not establish retrieval readiness" in prepared.premise
    assert "Deployment in 2026" in prepared.premise
    assert "Backups" not in prepared.premise
    assert prepared.claim == "Health proves retrieval readiness."  # No repair of the claim.
    assert_original_spans(prepared, evidence)


TABLE = """# Reimbursement for 2026

Amounts are in USD per night and apply to approved travel only.

| Item | Limit | Status |
| --- | ---: | --- |
| Hotel | 250 | Planned, not approved |
| Meals | 40 | Approved |
| Taxi | 90 | Approved |

[^1]: A manager must approve the trip before departure.

## Other policy

An unrelated paragraph.
"""


def test_table_keeps_owner_header_unit_status_caption_and_footnote_without_other_rows():
    evidence = [source(TABLE)]
    prepared = build_verification_inputs(binding(evidence, [(1, "250")]), evidence)[0]
    for required in ("Reimbursement for 2026", "USD per night", "approved travel only", "| Item | Limit | Status |",
                     "| Hotel | 250 | Planned, not approved |", "[^1]: A manager must approve"):
        assert required in prepared.premise
    for excluded in ("| Meals |", "| Taxi |", "An unrelated paragraph"):
        assert excluded not in prepared.premise
    assert_original_spans(prepared, evidence)


def test_two_quotes_in_one_table_keep_both_rows_in_original_order_and_one_header():
    prepared = prepare(TABLE, "250")
    evidence = [source(TABLE)]
    report = binding(evidence, [(1, "90"), (1, "250")])
    prepared = build_verification_inputs(report, evidence)[0]
    assert len(prepared.sources) == 1 and len(prepared.sources[0].anchors) == 2
    assert prepared.premise.index("| Hotel |") < prepared.premise.index("| Taxi |")
    assert prepared.premise.count("| Item | Limit | Status |") == 1
    assert "| Meals |" not in prepared.premise


def test_quote_covering_multiple_rows_is_never_narrowed_to_a_favored_row():
    quote = "| Hotel | 250 | Planned, not approved |\n| Meals | 40 | Approved |"
    prepared = prepare(TABLE, quote)
    assert quote in prepared.premise


def test_empty_cell_retains_full_table_instead_of_inventing_inherited_row_label():
    text = "| Owner | Limit |\n| --- | --- |\n| Team A | 2 |\n|  | 3 |\n| Team B | 4 |"
    prepared = prepare(text, "|  | 3 |")
    assert prepared.status == "ready"
    assert "Team A" in prepared.premise and "Team B" in prepared.premise


def test_escaped_and_inline_code_pipes_do_not_change_column_roles():
    text = "| Tool | Status |\n| --- | --- |\n| `a|b` and a\\|b | Not ready |\n| Other | Ready |"
    prepared = prepare(text, "Not ready")
    assert prepared.status == "ready"
    assert "`a|b` and a\\|b" in prepared.premise
    assert "| Other |" not in prepared.premise


def test_setext_scope_heading_is_retained():
    text = "Policy for 2026\n===\n\nHotels\n---\n\nThe limit is 250 USD."
    prepared = prepare(text, "250 USD")
    assert "Policy for 2026" in prepared.premise and "Hotels" in prepared.premise


def test_fenced_code_is_not_mistaken_for_markdown_table_or_heading():
    text = "# Syntax\n\n```text\n| Item | Limit |\n| --- | --- |\n| Hotel | 250 |\n```\n\n# Other\n\nOther context."
    prepared = prepare(text, "Hotel")
    assert "```text" in prepared.premise and prepared.premise.count("```") == 2
    assert "Other context" not in prepared.premise


def test_html_table_is_retained_losslessly_without_inventing_column_meanings():
    text = "<table>\n<tr><th>Item</th><th>Limit</th></tr>\n\n<tr><td>Hotel</td><td>250</td></tr>\n</table>\n\nNote: USD only."
    prepared = prepare(text, "250")
    assert prepared.status == "ready"
    assert "<th>Item</th>" in prepared.premise and "</table>" in prepared.premise
    assert "USD only" in prepared.premise


@pytest.mark.parametrize("text,quote,reason", [
    ("| Hotel | 250 |", "250", "table_structure_unavailable"),
    ("| Item | Limit |\n| --- | --- |\n| Hotel | 250 |", "Item", "table_anchor_without_data_row"),
])
def test_incomplete_table_context_is_unusable(text, quote, reason):
    prepared = prepare(text, quote)
    assert prepared.status == "needs_review" and prepared.reason == reason
    assert prepared.premise == ""


def test_distinct_sources_in_same_document_keep_chunk_identity_and_joint_context():
    evidence = [source("The rate is 2 USD per unit.", chunk="rate"), source("The order has 3 units.", chunk="quantity")]
    report = binding(evidence, [(1, "2 USD"), (2, "3 units")], text="The order costs 6 USD.")
    prepared = build_verification_inputs(report, evidence)[0]
    assert prepared.status == "ready" and len(prepared.sources) == 2
    assert {s.provenance["chunk_id"] for s in prepared.sources} == {"rate", "quantity"}
    assert "2 USD" in prepared.premise and "3 units" in prepared.premise
    assert_original_spans(prepared, evidence)


def test_repeated_quote_uses_bound_offset_instead_of_searching_again():
    text = "# First\n\nApproved.\n\n# Second\n\nApproved."
    evidence = [source(text)]
    report = binding(evidence, [(1, "Approved.")])
    support = report["claims"][0]["supports"][0]
    support.update(source_start=text.rindex("Approved."), source_end=len(text))
    prepared = build_verification_inputs(report, evidence)[0]
    assert "# Second" in prepared.premise and "# First" not in prepared.premise


@pytest.mark.parametrize("field", ["doc_id", "chunk_id", "evidence_ref", "content_hash", "source_version", "source_scope"])
def test_changed_source_binding_is_not_repaired_by_matching_text(field):
    evidence = [source("The limit is 3 days.")]
    report = binding(evidence, [(1, "3 days")])
    evidence[0][field] = "changed"
    prepared = build_verification_inputs(report, evidence)[0]
    assert prepared.status == "needs_review" and prepared.reason == "binding_source_changed"
    assert prepared.premise == ""


def test_changed_offsets_are_not_relocated():
    evidence = [source("The limit is 3 days.")]
    report = binding(evidence, [(1, "3 days")])
    report["claims"][0]["supports"][0]["source_start"] = 0
    prepared = build_verification_inputs(report, evidence)[0]
    assert prepared.reason == "binding_excerpt_changed" and not prepared.premise


def test_unknown_lineage_is_not_backfilled():
    evidence = [source("The limit is 3 days.", source_version=None)]
    report = binding(evidence, [(1, "3 days")])
    prepared = build_verification_inputs(report, evidence)[0]
    assert prepared.reason == "source_lineage_missing" and not prepared.premise


def test_image_binding_is_not_presented_as_text_validation():
    evidence = [source("Original image.", content_kind="file")]
    draft = GroundedAnswer.model_validate({"answer":"The chart shows growth.","claims":[{"text":"The chart shows growth.",
        "supports":[{"citation_id":1,"image_region":[0.0,0.0,1.0,1.0]}]}]})
    report = validate_grounded_answer(draft, evidence)
    assert report["valid"]
    assert build_verification_inputs(report, evidence)[0].reason == "text_context_unavailable"


def test_one_unusable_support_does_not_allow_partial_joint_support():
    evidence = [source("The rate is 2 USD.", chunk="one"), source("There are 3 units.", chunk="two")]
    report = binding(evidence, [(1, "2 USD"), (2, "3 units")])
    evidence[1]["content_hash"] = "changed"
    prepared = build_verification_inputs(report, evidence)[0]
    assert prepared.status == "needs_review" and not prepared.premise


def test_context_budget_does_not_trim_away_late_negation():
    text = "The service is available. " + "Scope remains unchanged. "*20 + "It is not approved for production."
    prepared = prepare(text, "available", max_context_chars=80)
    assert prepared.reason == "context_budget_exceeded" and not prepared.premise
    assert "not approved for production" in prepared.sources[0].text


def test_token_budget_counts_complete_joint_premise_and_unchanged_claim():
    seen = []
    def counter(premise, claim):
        seen.append((premise, claim))
        return 513
    prepared = prepare("The limit is 3 days.", "3 days", token_counter=counter)
    assert prepared.reason == "input_token_budget_exceeded" and prepared.input_tokens == 513
    assert not prepared.premise
    assert seen[0][1] == prepared.claim and "[Evidence 1]" in seen[0][0]


def test_builder_is_request_local_and_does_not_mutate_bindings_or_evidence():
    evidence = [source("The limit is 3 days.")]
    report = binding(evidence, [(1, "3 days")])
    before = deepcopy((report, evidence))
    first = build_verification_inputs(report, evidence)[0]
    second = build_verification_inputs(report, evidence)[0]
    assert (report, evidence) == before
    assert asdict(first) == asdict(second)
    first.sources[0].provenance["doc_id"] = "local-only"
    assert second.sources[0].provenance["doc_id"] == "policy" and evidence[0]["doc_id"] == "policy"


def test_invalid_binding_cannot_be_promoted_to_classifier_input():
    with pytest.raises(ValueError, match="valid_binding_report_required"):
        build_verification_inputs({"valid":False,"claims":[]}, [])
