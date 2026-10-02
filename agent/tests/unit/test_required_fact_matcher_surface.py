"""Pins the deterministic fact matcher's inflection blind spot.

Why this exists
---------------
The plan replaces the LLM *judge* with ``required_fact_coverage`` and adds a
guard that compares coverage before/after a repair. Both decisions inherit every
false negative of that matcher, so its surface has to be known and regression
tested -- not just described in a report.

``_identifier_tokens`` / ``required_fact_match_details``
(``eval/agent_metrics.py:59-99``) match a required-fact alias in one of two ways:

1. ``normalized_alias`` -- NFKC + casefold + strip non-word, then substring
2. ``identifier_tokens`` -- camelCase split; the alias's tokens (len >= 2) must
   be a **subset** of the answer's tokens

Measured over the dataset's 141 aliases: separators, casing, camelCase,
backticks and word order all match 100%, while **pluralised forms match 62% and
singularised forms 83%**. Path 2 is set-based, so ``sub_queries`` -> {sub,
queries} cannot match an answer that says "sub query".

These tests pin concrete examples of both paths and both failure modes, giving
the "add word-form normalization" work (10.2-1a of the final report) a
CI-visible definition of done: fix the matcher and these flip deliberately.
"""

import pytest

from agent.answer.fact_coverage import required_fact_coverage, required_fact_match_details

pytestmark = pytest.mark.no_storage


def _hit(answer: str, term: str) -> bool:
    return required_fact_coverage(answer, [[term]])[1][0]


def _match_type(answer: str, term: str) -> str | None:
    return required_fact_match_details(answer, [[term]])[0]["match_type"]


@pytest.mark.parametrize(
    "answer",
    [
        "The ToolRegistryAdapter is used here.",
        "The tool registry adapter is used here.",
        "The tool_registry_adapter is used here.",
        "The `ToolRegistryAdapter` is used here.",
        "Here the Tool Registry Adapter is mentioned.",
    ],
)
def test_separator_and_case_variants_match(answer: str) -> None:
    """Formatting is not a source of false negatives."""
    assert _hit(answer, "ToolRegistryAdapter") is True


def test_word_order_is_not_a_source_of_false_negatives() -> None:
    """Path 2 is a token set, so order is irrelevant."""
    assert _hit("Adapter for the Tool Registry, the ToolRegistryAdapter.", "ToolRegistryAdapter") is True


@pytest.mark.parametrize(
    ("answer", "term"),
    [
        ("Each sub query is routed separately.", "sub_queries"),
        ("The filter is applied to the query plan.", "filters"),
    ],
)
def test_inflection_changes_are_matched(answer: str, term: str) -> None:
    """Singular/plural surface forms of the same identifier must count as hits."""
    assert _hit(answer, term) is True
    assert _match_type(answer, term) in {"inflection", "identifier_tokens", "normalized_alias"}


def test_alias_gap_is_NOT_matched() -> None:
    """Second blind spot: the alias list can simply miss a valid paraphrase.

    ``local_quality_tool_registry`` requires ``["不维护第二份", "second tool
    dictionary"]`` while the pipeline answer says "preventing a duplicate
    registry" -- semantically complete, scored as a miss.
    """
    assert _hit("Preventing a duplicate registry [4].", "second tool dictionary") is False
    assert _hit("Preventing a duplicate registry [4].", "不维护第二份") is False


def test_single_token_aliases_fall_back_to_substring() -> None:
    """One-token aliases (e.g. ``Toolset``) only ever get path 1."""
    assert _match_type("The Toolset layer owns it.", "Toolset") == "normalized_alias"
    assert _match_type("The 'Toolset' layer owns it.", "Toolset") == "normalized_alias"
    assert _hit("The toolset layer owns it.", "Toolset") is True
