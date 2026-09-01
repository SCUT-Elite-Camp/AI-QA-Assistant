import json
import re
from typing import Any

from agent.answer.complexity import requires_complex_answer
from agent.answer.schemas import AnswerCompletenessResult
from agent.llm.base import BaseLLM
from agent.schemas.query_plan import QueryPlan
from agent.schemas.tool_execution import Evidence


class AnswerCompletenessChecker:
    """Check and repair answer omissions using accepted evidence only."""

    _MAX_EVIDENCE_ITEMS = 10
    _MAX_CONTENT_CHARS = 2400

    def __init__(self, llm: BaseLLM) -> None:
        self.llm = llm

    def check(
        self,
        query_plan: QueryPlan,
        answer: str,
        evidence: list[Evidence],
    ) -> AnswerCompletenessResult:
        if not evidence:
            return AnswerCompletenessResult(
                complete=True,
                reason="no_evidence_to_check",
                check_performed=False,
            )

        if not self.requires_llm_check(query_plan):
            return self._deterministic_check(answer, evidence)

        response = self.llm.chat(
            [{"role": "system", "content": self._check_prompt(query_plan, answer, evidence)}],
            tools=None,
        )
        payload = self._parse_json_response(response)
        return AnswerCompletenessResult.model_validate(payload)

    @staticmethod
    def requires_llm_check(query_plan: QueryPlan) -> bool:
        """Reserve semantic completeness review for genuinely complex answers."""
        return requires_complex_answer(query_plan)

    @staticmethod
    def _deterministic_check(
        answer: str,
        evidence: list[Evidence],
    ) -> AnswerCompletenessResult:
        """Apply a cheap structural gate to a single-target evidence answer."""
        citation_numbers = [int(value) for value in re.findall(r"\[(\d+)\]", answer)]
        valid_citations = [
            value for value in citation_numbers if 1 <= value <= len(evidence)
        ]
        if not valid_citations:
            return AnswerCompletenessResult(
                complete=False,
                missing_aspects=["citation_to_accepted_evidence"],
                reason="deterministic_check_missing_valid_citation",
                check_performed=True,
            )
        return AnswerCompletenessResult(
            complete=True,
            reason="deterministic_single_target_check_passed",
            check_performed=True,
        )

    def repair(
        self,
        query_plan: QueryPlan,
        answer: str,
        evidence: list[Evidence],
        result: AnswerCompletenessResult,
    ) -> str:
        response = self.llm.chat(
            [{"role": "system", "content": self._repair_prompt(query_plan, answer, evidence, result)}],
            tools=None,
        )
        content = response.get("content", "") if isinstance(response, dict) else ""
        return content.strip() if isinstance(content, str) else ""

    def _check_prompt(
        self,
        query_plan: QueryPlan,
        answer: str,
        evidence: list[Evidence],
    ) -> str:
        targets = query_plan.sub_queries or [query_plan.standalone_query]
        return (
            "You are an answer completeness checker. Judge only whether the answer covers "
            "the user's requested aspects and material facts explicitly present in the supplied "
            "evidence. Pay special attention to percentages, monetary amounts, dates, named "
            "entities, and comparison sides. Never require a fact absent from the evidence. "
            "Return JSON only with keys: complete (boolean), missing_aspects (string array), "
            "missing_critical_facts (string array), reason (string), check_performed (true).\n\n"
            f"Question: {query_plan.standalone_query}\n"
            f"Required aspects: {json.dumps(targets, ensure_ascii=False)}\n"
            f"Answer: {answer}\n\n"
            f"Evidence:\n{self._format_evidence(evidence)}"
        )

    def _repair_prompt(
        self,
        query_plan: QueryPlan,
        answer: str,
        evidence: list[Evidence],
        result: AnswerCompletenessResult,
    ) -> str:
        return (
            "Repair the answer exactly once using only the supplied evidence. Add the listed "
            "omissions, preserve correct existing content, and keep citation markers [n] aligned "
            "with the numbered evidence. Do not mention this review and do not invent facts. "
            "Return only the repaired answer.\n\n"
            f"Question: {query_plan.standalone_query}\n"
            f"Original answer: {answer}\n"
            f"Missing aspects: {json.dumps(result.missing_aspects, ensure_ascii=False)}\n"
            "Missing critical facts: "
            f"{json.dumps(result.missing_critical_facts, ensure_ascii=False)}\n\n"
            f"Evidence:\n{self._format_evidence(evidence)}"
        )

    def _format_evidence(self, evidence: list[Evidence]) -> str:
        rows: list[str] = []
        for index, item in enumerate(evidence[: self._MAX_EVIDENCE_ITEMS], start=1):
            content = item.content[: self._MAX_CONTENT_CHARS]
            rows.append(f"[{index}] {item.title}: {content}")
        return "\n".join(rows)

    @staticmethod
    def _parse_json_response(response: Any) -> dict[str, Any]:
        if not isinstance(response, dict):
            raise ValueError("completeness checker returned a non-object response")
        content = response.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("completeness checker returned empty content")
        text = content.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
        if fenced:
            text = fenced.group(1)
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("completeness checker JSON must be an object")
        return payload
