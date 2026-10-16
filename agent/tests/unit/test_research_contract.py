import pytest
from pydantic import ValidationError

from agent.schemas.research import (
    ResearchPlan,
    ResearchPlanValidationError,
    ResearchPlanValidator,
    ResearchRequest,
)
from deep_research.planner import ModelResearchPlanner, PlannerError


@pytest.fixture
def plan_payload() -> dict:
    return {
        "research_id": "plan-validation",
        "objective": "核验部署状态",
        "source_scope": {"document_ids": ["doc-1"]},
        "tasks": [{
            "task_id": "task-1", "question": "部署状态是什么？",
            "purpose": "核验部署记录", "source_ids": ["doc-1"],
            "acceptance_criteria": [{"criterion_id": "status", "description": "找到部署状态原文"}],
        }],
    }


def test_valid_plan_preserves_explicit_source_scope(plan_payload: dict) -> None:
    plan = ResearchPlan.model_validate(plan_payload)
    ResearchPlanValidator.validate_or_raise(plan)
    assert plan.source_scope.document_ids == ["doc-1"]
    assert plan.tasks[0].source_ids == ["doc-1"]


@pytest.mark.parametrize(
    ("case", "error_code"),
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
def test_invalid_plan_returns_stable_error_code(plan_payload: dict, case: str, error_code: str) -> None:
    task = plan_payload["tasks"][0]
    if case == "empty_tasks":
        plan_payload["tasks"] = []
    elif case in {"duplicate_task_id", "duplicate_task_question", "dependency_cycle", "over_budget"}:
        other = {**task, "task_id": "task-2", "question": "有哪些发布风险？"}
        plan_payload["tasks"].append(other)
        if case == "duplicate_task_id":
            other["task_id"] = task["task_id"]
        elif case == "duplicate_task_question":
            other["question"] = task["question"]
        elif case == "dependency_cycle":
            task["dependencies"] = ["task-2"]
            other["dependencies"] = ["task-1"]
        else:
            plan_payload["budget"] = {"max_tasks": 1}
    elif case == "unauthorized_tool":
        task["allowed_tools"] = ["write_document"]
    elif case == "out_of_scope_source":
        task["source_ids"] = ["forbidden"]
    elif case == "missing_acceptance_criteria":
        task["acceptance_criteria"] = []

    plan = ResearchPlan.model_validate(plan_payload)
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

    request = ResearchRequest.model_validate({"query": "研究资料", "source_scope": {}})
    assert request.source_scope.all_documents is True
    assert request.source_scope.document_ids == []

    with pytest.raises(ValidationError, match="research_source_scope_ambiguous"):
        ResearchRequest.model_validate({"query": "研究资料", "source_scope": {
            "all_documents": True, "document_ids": ["doc-1"],
        }})


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


def test_model_plan_must_cover_the_user_objective(plan_payload: dict) -> None:
    plan = ResearchPlan.model_validate(plan_payload)

    with pytest.raises(PlannerError, match="does not cover"):
        ModelResearchPlanner._validate_task_coverage(
            "compare W30 and W34 delivery metrics",
            plan.tasks,
        )
