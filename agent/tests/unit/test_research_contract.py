import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.schemas.research import (
    ResearchPlan,
    ResearchPlanValidationError,
    ResearchPlanValidator,
    ResearchRequest,
)


FIXTURE_PATH = Path(__file__).resolve().parents[2] / "mock" / "research_contract_fixtures.json"


@pytest.fixture(scope="module")
def fixtures() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_research_request_and_three_plans_use_frozen_v1_contract(fixtures: dict) -> None:
    request = ResearchRequest.model_validate(fixtures["request"])
    assert request.schema_version == "research.v1"
    assert request.profile.value == "standard"
    assert request.source_scope.document_ids == ["cp2-goals", "cp2-plan"]

    plans = fixtures["valid_plans"]
    assert len(plans) >= 3
    for payload in plans.values():
        plan = ResearchPlan.model_validate(payload)
        ResearchPlanValidator.validate_or_raise(plan)
        assert plan.schema_version == "research.v1"


@pytest.mark.parametrize(
    ("fixture_name", "error_code"),
    [
        ("empty_tasks", "research_plan_empty_tasks"),
        ("duplicate_task_id", "research_plan_duplicate_task_id"),
        ("duplicate_task_question", "research_plan_duplicate_task_question"),
        ("dependency_cycle", "research_plan_dependency_cycle"),
        ("unauthorized_tool", "research_task_tool_not_allowed"),
        ("out_of_scope_source", "research_task_source_out_of_scope"),
        ("over_budget", "research_plan_task_budget_exceeded"),
        ("missing_acceptance_criteria", "research_task_acceptance_criteria_missing"),
    ],
)
def test_invalid_planner_fixture_returns_stable_error_code(
    fixtures: dict,
    fixture_name: str,
    error_code: str,
) -> None:
    plan = ResearchPlan.model_validate(fixtures["invalid_plans"][fixture_name])

    with pytest.raises(ResearchPlanValidationError) as exc_info:
        ResearchPlanValidator.validate_or_raise(plan)

    assert exc_info.value.code == error_code
    assert exc_info.value.issue.code == error_code


def test_research_contract_rejects_unknown_fields_and_external_source_ids() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ResearchRequest.model_validate(
            {
                "query": "研究本地资料",
                "source_scope": {"document_ids": ["doc-1"]},
                "unexpected": "research",
            }
        )

    with pytest.raises(ValidationError, match="source_scope_external_source_forbidden"):
        ResearchRequest.model_validate(
            {
                "query": "研究资料",
                "source_scope": {"document_ids": ["https://example.com"]},
            }
        )

    with pytest.raises(ValidationError, match="research_source_scope_required"):
        ResearchRequest.model_validate(
            {
                "query": "研究资料",
                "source_scope": {},
            }
        )


def test_empty_source_scope_has_a_deterministic_plan_error() -> None:
    plan = ResearchPlan.model_validate(
        {
            "research_id": "empty-scope",
            "objective": "没有显式来源范围",
            "source_scope": {},
            "tasks": [
                {
                    "task_id": "task-1",
                    "question": "问题",
                    "purpose": "验证来源范围",
                    "acceptance_criteria": [
                        {"criterion_id": "criterion-1", "description": "找到证据"}
                    ],
                }
            ],
        }
    )

    with pytest.raises(ResearchPlanValidationError) as exc_info:
        ResearchPlanValidator.validate_or_raise(plan)

    assert exc_info.value.code == "research_source_scope_required"
