import json
import re

from agent.answer.complexity import requires_complex_answer
from agent.answer.fact_coverage import missing_targets, required_fact_coverage
from agent.answer.schemas import AnswerCompletenessResult
from agent.answer.target_extractor import TargetExtractor
from agent.config.settings import settings
from agent.llm.base import BaseLLM
from agent.schemas.query_plan import QueryPlan
from agent.schemas.tool_execution import Evidence


class AnswerCompletenessChecker:
    """Gate answers with deterministic coverage, then repair omissions as a craftsman."""

    _MAX_EVIDENCE_ITEMS = 10
    _MAX_CONTENT_CHARS = 2400
    _REPAIR_EVIDENCE_ITEMS = 5
    _REPAIR_CONTENT_CHARS = 1200

    def __init__(
        self,
        llm: BaseLLM,
        *,
        target_extractor: TargetExtractor | None = None,
    ) -> None:
        self.llm = llm
        self.target_extractor = target_extractor or TargetExtractor(llm)

    def check(
        self,
        query_plan: QueryPlan,
        answer: str,
        evidence: list[Evidence],
        *,
        use_llm_extract: bool | None = None,
    ) -> AnswerCompletenessResult:
        if not evidence:
            return AnswerCompletenessResult(
                complete=True,
                reason="no_evidence_to_check",
                check_performed=False,
                skip_reason="no_evidence",
            )

        used_llm_extract = False
        extract_llm = (
            settings.ANSWER_TARGET_EXTRACT_LLM
            if use_llm_extract is None
            else use_llm_extract
        )
        if extract_llm and requires_complex_answer(query_plan):
            used_llm_extract = True
        targets = self.target_extractor.extract(query_plan, evidence, use_llm=extract_llm)
        citation_ok = self._has_valid_citation(answer, evidence)

        if not targets:
            result = self._deterministic_check(answer, evidence)
            result.used_llm_extract = used_llm_extract
            return result

        coverage, _hits = required_fact_coverage(answer, [[target] for target in targets])
        missing = missing_targets(answer, targets)
        if not missing and citation_ok:
            return AnswerCompletenessResult(
                complete=True,
                reason="deterministic_coverage_check_passed",
                check_performed=True,
                required_targets=targets,
                coverage=coverage,
                used_llm_extract=used_llm_extract,
            )

        missing_aspects = list(missing)
        if not citation_ok and "citation_to_accepted_evidence" not in missing_aspects:
            missing_aspects.append("citation_to_accepted_evidence")
        missing_facts = [item for item in missing if _looks_like_critical_fact(item)]
        return AnswerCompletenessResult(
            complete=False,
            missing_aspects=missing_aspects,
            missing_critical_facts=missing_facts,
            reason=(
                "deterministic_coverage_gap"
                if missing
                else "deterministic_check_missing_valid_citation"
            ),
            check_performed=True,
            required_targets=targets,
            coverage=coverage,
            used_llm_extract=used_llm_extract,
        )

    @staticmethod
    def requires_llm_check(query_plan: QueryPlan) -> bool:
        """True when the query is complex enough to justify LLM target extraction."""
        return requires_complex_answer(query_plan)

    @staticmethod
    def _has_valid_citation(answer: str, evidence: list[Evidence]) -> bool:
        citation_numbers = [int(value) for value in re.findall(r"\[(\d+)\]", answer)]
        return any(1 <= value <= len(evidence) for value in citation_numbers)

    def _deterministic_check(
        self,
        answer: str,
        evidence: list[Evidence],
    ) -> AnswerCompletenessResult:
        """Cheap structural gate when no atomic targets could be derived."""
        if not self._has_valid_citation(answer, evidence):
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
        missing = list(dict.fromkeys([*result.missing_aspects, *result.missing_critical_facts]))
        repair_evidence = self._evidence_for_repair(evidence, missing)
        response = self.llm.chat(
            [{
                "role": "system",
                "content": self._repair_prompt(query_plan, answer, repair_evidence, result),
            }],
            tools=None,
        )
        content = response.get("content", "") if isinstance(response, dict) else ""
        return content.strip() if isinstance(content, str) else ""

    def _repair_prompt(
        self,
        query_plan: QueryPlan,
        answer: str,
        evidence: list[Evidence],
        result: AnswerCompletenessResult,
    ) -> str:
        style = (
            "Add the listed omissions onto the original answer. Preserve every correct "
            "sentence already present. Do not rewrite from scratch. Prefer appending "
            "missing facts with citation markers [n] aligned with the numbered evidence."
            if settings.ANSWER_REPAIR_APPEND_ONLY
            else "Repair the answer exactly once using only the supplied evidence."
        )
        return (
            f"{style} Do not mention this review and do not invent facts. "
            "Return only the repaired answer.\n\n"
            f"Question: {query_plan.standalone_query}\n"
            f"Original answer: {answer}\n"
            f"Missing aspects: {json.dumps(result.missing_aspects, ensure_ascii=False)}\n"
            "Missing critical facts: "
            f"{json.dumps(result.missing_critical_facts, ensure_ascii=False)}\n\n"
            f"Evidence:\n{self._format_evidence(evidence)}"
        )

    def _evidence_for_repair(
        self,
        evidence: list[Evidence],
        missing: list[str],
    ) -> list[Evidence]:
        terms = [item for item in missing if item != "citation_to_accepted_evidence"]
        if not terms:
            return evidence[: self._REPAIR_EVIDENCE_ITEMS]
        selected: list[Evidence] = []
        for item in evidence:
            blob = f"{item.title}\n{item.content}"
            if missing_targets(blob, terms) != terms:
                selected.append(item)
            if len(selected) >= self._REPAIR_EVIDENCE_ITEMS:
                break
        return selected or evidence[: self._REPAIR_EVIDENCE_ITEMS]

    def _format_evidence(self, evidence: list[Evidence]) -> str:
        rows: list[str] = []
        limit = self._REPAIR_CONTENT_CHARS
        for index, item in enumerate(evidence[: self._MAX_EVIDENCE_ITEMS], start=1):
            rows.append(f"[{index}] {item.title}: {item.content[:limit]}")
        return "\n".join(rows)


def _looks_like_critical_fact(term: str) -> bool:
    return bool(re.search(r"\d|%", term) or re.search(r"[A-Z].*[a-z].*[A-Z]", term))
