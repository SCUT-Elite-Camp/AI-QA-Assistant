from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from agent.exploration.schemas import CoverageAssessment, ExplorationAction
from agent.schemas.query_plan import QueryIntent, QueryPlan
from agent.schemas.tool_execution import Evidence


class CoverageAssessor:
    """Judge evidence breadth separately from evidence validity.

    This deterministic assessor is the safe fallback for local/private data. A
    future structured-output LLM assessor can implement the same contract, but
    its failure must fall back here rather than silently treating five nearby
    chunks as complete coverage.
    """

    _BROAD_MARKERS = (
        "完成了什么", "有哪些工作", "全部", "整体", "系统性", "综合", "总结",
        "跨章节", "跨文档", "比较", "对比", "演变", "脉络", "分别",
        "what has", "all work", "overall", "comprehensive", "summarize",
        "across sections", "across documents", "compare", "evolution",
    )

    def assess(
        self,
        query_plan: QueryPlan,
        evidence: Iterable[Evidence],
        *,
        exploration_mode: str = "auto",
        available_actions: Iterable[str] = (),
    ) -> CoverageAssessment:
        items = self._deduplicate(evidence)
        documents = {item.document_id or item.doc_id for item in items}
        sections = {
            self._section_key(item)
            for item in items
            if self._section_key(item)
        }
        complex_query = self._is_complex(query_plan)
        missing: list[str] = []

        comparison_targets = [value.casefold() for value in query_plan.sub_queries]
        for target in comparison_targets:
            if not any(item.retrieval_query.casefold() == target for item in items):
                missing.append(target)

        if not items:
            missing.append("authoritative_evidence")
        if self._needs_cross_document(query_plan):
            if len(documents) < 2:
                missing.append("cross_document_coverage")
        if complex_query and len(items) < 3:
            missing.append("evidence_breadth")
        if complex_query and len(sections) < 2:
            missing.append("topic_coverage")

        missing = list(dict.fromkeys(missing))
        sufficient = not missing
        available = set(available_actions)
        actions: list[ExplorationAction] = []
        if (
            {"cross_document_coverage", "evidence_breadth", "topic_coverage"}
            & set(missing)
            and ExplorationAction.WIKI_SEARCH in available
        ):
            actions.append(ExplorationAction.WIKI_SEARCH)

        mode = exploration_mode.casefold()
        should_explore = (
            mode != "off"
            and bool(actions)
            and ((complex_query and not sufficient) or mode == "force")
        )
        return CoverageAssessment(
            complex_query=complex_query,
            sufficient=sufficient,
            should_explore=should_explore,
            covered_facets=[
                f"documents:{len(documents)}",
                f"sections:{len(sections)}",
                f"evidence:{len(items)}",
            ],
            missing_facets=missing,
            recommended_actions=actions if should_explore else [],
            unique_documents=len(documents),
            unique_sections=len(sections),
            unique_evidence=len(items),
            reason=(
                "coverage_sufficient"
                if sufficient and mode != "force"
                else "forced_exploration" if mode == "force" and actions
                else "coverage_gaps_detected"
            ),
        )

    @classmethod
    def _is_complex(cls, plan: QueryPlan) -> bool:
        query = plan.standalone_query.casefold()
        return (
            plan.intent in {QueryIntent.SUMMARIZATION, QueryIntent.COMPARISON}
            or bool(plan.sub_queries)
            or any(marker in query for marker in cls._BROAD_MARKERS)
        )

    @staticmethod
    def _needs_cross_document(plan: QueryPlan) -> bool:
        query = plan.standalone_query.casefold()
        return (
            plan.intent == QueryIntent.COMPARISON
            or "跨文档" in query
            or "across documents" in query
        )

    @staticmethod
    def _section_key(item: Evidence) -> str:
        locator = item.locator or {}
        section_id = str(locator.get("section_id") or "")
        if section_id:
            return section_id
        section_ids = locator.get("section_ids") or []
        if isinstance(section_ids, list) and section_ids:
            return "|".join(sorted(str(value) for value in section_ids if str(value)))
        path = locator.get("section_path") or []
        if isinstance(path, str):
            return path.strip()
        if isinstance(path, list):
            return " / ".join(str(value).strip() for value in path if str(value).strip())
        return ""

    @staticmethod
    def _deduplicate(evidence: Iterable[Evidence]) -> list[Evidence]:
        best: dict[tuple[str, str], Evidence] = {}
        content_seen: set[str] = set()
        for item in sorted(evidence, key=lambda value: value.score, reverse=True):
            normalized = re.sub(r"\s+", " ", item.content).strip().casefold()
            content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            if content_hash in content_seen:
                continue
            content_seen.add(content_hash)
            best.setdefault((item.doc_id, item.chunk_id), item)
        return list(best.values())
