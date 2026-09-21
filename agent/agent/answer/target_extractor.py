"""Derive atomic answer targets from a QueryPlan and accepted evidence."""

from __future__ import annotations

import json
import re
from typing import Any

from agent.answer.complexity import requires_complex_answer
from agent.answer.fact_coverage import identifier_tokens, normalized_fact_text
from agent.config.settings import settings
from agent.llm.base import BaseLLM
from agent.schemas.query_plan import QueryPlan
from agent.schemas.tool_execution import Evidence


_CAMEL = re.compile(r"\b[A-Za-z][a-z0-9]*(?:[A-Z][a-z0-9]*)+\b")
_SNAKE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b")
_BACKTICK = re.compile(r"`([^`\n]{2,80})`")
_PERCENT = re.compile(r"\b\d+(?:\.\d+)?%")
_MONEY = re.compile(r"\$\d[\d,]*(?:\.\d+)?")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_QUANTITY_HINT = re.compile(
    r"share|percent|percentage|ratio|amount|revenue|占比|比例|百分比|多少",
    re.IGNORECASE,
)
_STOPWORDS = {
    "what", "which", "who", "whom", "when", "where", "why", "how",
    "the", "and", "or", "for", "from", "with", "that", "this", "are",
    "was", "were", "does", "did", "can", "into", "about", "your", "user",
    "please", "give", "list", "name", "core", "main", "full", "complete",
}


class TargetExtractor:
    """Build a short, checkable target list. Lexical first; LLM extract is optional."""

    _MAX_TARGETS = 12
    _MAX_EVIDENCE_ITEMS = 8
    _MAX_CONTENT_CHARS = 1200

    def __init__(self, llm: BaseLLM | None = None) -> None:
        self.llm = llm

    def extract(
        self,
        query_plan: QueryPlan,
        evidence: list[Evidence],
        *,
        use_llm: bool | None = None,
    ) -> list[str]:
        lexical = self.lexical_targets(query_plan, evidence)
        if use_llm is None:
            use_llm = settings.ANSWER_TARGET_EXTRACT_LLM
        if not use_llm or self.llm is None:
            return lexical[: self._MAX_TARGETS]
        if lexical and not requires_complex_answer(query_plan):
            return lexical[: self._MAX_TARGETS]
        extracted = self._llm_targets(query_plan, evidence)
        return _dedupe(lexical + extracted)[: self._MAX_TARGETS]

    def lexical_targets(self, query_plan: QueryPlan, evidence: list[Evidence]) -> list[str]:
        query = _query_text(query_plan)
        evidence_text = "\n".join(
            f"{item.title}\n{item.content}" for item in evidence[: self._MAX_EVIDENCE_ITEMS]
        )
        query_norm = normalized_fact_text(query)
        query_tokens = identifier_tokens(query)
        candidates: list[str] = []

        for source, require_query_grounding in (
            (query, False),
            (evidence_text, True),
        ):
            for term in _scan_terms(source):
                if require_query_grounding and not _grounded_in_query(term, query_norm, query_tokens):
                    continue
                candidates.append(term)

        if _QUANTITY_HINT.search(query):
            candidates.extend(_PERCENT.findall(evidence_text))
            candidates.extend(_MONEY.findall(evidence_text))

        years_in_query = set(_YEAR.findall(query))
        candidates.extend(year for year in _YEAR.findall(evidence_text) if year in years_in_query)
        return _dedupe(candidates)[: self._MAX_TARGETS]

    def _llm_targets(self, query_plan: QueryPlan, evidence: list[Evidence]) -> list[str]:
        if self.llm is None:
            return []
        prompt = (
            "Extract the atomic facts the answer MUST mention. Use only the question and "
            "evidence. Each item must be a short identifier, field name, entity, number, "
            "date, or comparison side. Never emit a whole sentence. Never invent facts "
            "absent from the evidence. Return JSON only with key required_facts "
            "(string array, max 12).\n\n"
            f"Question: {query_plan.standalone_query}\n"
            f"Sub-queries: {json.dumps(query_plan.sub_queries or [], ensure_ascii=False)}\n"
            f"Evidence:\n{self._format_evidence(evidence)}"
        )
        response = self.llm.chat([{"role": "system", "content": prompt}], tools=None)
        payload = _parse_json_object(response)
        facts = payload.get("required_facts")
        if not isinstance(facts, list):
            return []
        return [item.strip() for item in facts if isinstance(item, str) and item.strip()]

    def _format_evidence(self, evidence: list[Evidence]) -> str:
        rows: list[str] = []
        for index, item in enumerate(evidence[: self._MAX_EVIDENCE_ITEMS], start=1):
            rows.append(f"[{index}] {item.title}: {item.content[: self._MAX_CONTENT_CHARS]}")
        return "\n".join(rows)


def _query_text(query_plan: QueryPlan) -> str:
    parts = [query_plan.original_query, query_plan.standalone_query, *(query_plan.sub_queries or [])]
    return "\n".join(part for part in parts if part)


def _scan_terms(text: str) -> list[str]:
    found: list[str] = []
    found.extend(match.group(1) for match in _BACKTICK.finditer(text))
    found.extend(_CAMEL.findall(text))
    found.extend(_SNAKE.findall(text))
    found.extend(_PERCENT.findall(text))
    found.extend(_MONEY.findall(text))
    return found


def _grounded_in_query(term: str, query_norm: str, query_tokens: set[str]) -> bool:
    term_norm = normalized_fact_text(term)
    if term_norm and term_norm in query_norm:
        return True
    term_tokens = identifier_tokens(term)
    return bool(term_tokens and term_tokens & query_tokens)


def _dedupe(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        cleaned = term.strip().strip("`")
        key = normalized_fact_text(cleaned)
        if not cleaned or key in seen or cleaned.casefold() in _STOPWORDS:
            continue
        seen.add(key)
        unique.append(cleaned)
    return unique


def _parse_json_object(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    content = response.get("content")
    if not isinstance(content, str) or not content.strip():
        return {}
    text = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
