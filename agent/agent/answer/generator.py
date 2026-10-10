"""Shared answer-model routing for the Fast and Thinking execution strategies."""

import logging
import re
from typing import Any, Literal

from agent.answer.complexity import answer_complexity_reasons
from agent.llm.base import BaseLLM
from agent.prompt.templates import ANSWER_RULES, SYSTEM_ROLE
from agent.schemas.query_plan import QueryPlan

logger = logging.getLogger("agent-layer")
AnswerModelPreference = Literal["auto", "fast", "complex"]


class AnswerGenerator:
    def __init__(
        self,
        *,
        complex_llm: BaseLLM,
        fast_llm: BaseLLM | None = None,
    ) -> None:
        self.complex_llm = complex_llm
        self.fast_llm = fast_llm

    @staticmethod
    def build_evidence_messages(
        query_plan: QueryPlan,
        evidence: list[dict[str, Any]],
        history: list[dict[str, Any]],
        *,
        is_first_message: bool = False,
        soul_content: str | None = None,
        preserve_evidence_order: bool = False,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Build the one authoritative-evidence prompt shared by both loops."""
        ordered_evidence = list(evidence)
        if not preserve_evidence_order:
            ordered_evidence = AnswerGenerator._prioritize_evidence(
                query_plan.standalone_query or query_plan.original_query,
                ordered_evidence,
            )
        blocks = []
        for index, item in enumerate(ordered_evidence, start=1):
            try:
                score = float(item.get("score", 0.0))
            except (TypeError, ValueError):
                score = 0.0
            blocks.append(
                f"[{index}] title: {item.get('title', '')}\n"
                f"doc_id: {item.get('doc_id', '')}\n"
                f"chunk_id: {item.get('chunk_id', '')}\n"
                f"content: {item.get('chunk_text', item.get('content', ''))}\n"
                f"score: {score:.4f}"
            )
        evidence_context = "\n\n".join(blocks) or "No relevant documents found."
        context_history = [
            {"role": item.get("role"), "content": item.get("content")}
            for item in history
            if item.get("role") in {"system", "user", "assistant"}
            and isinstance(item.get("content"), str)
        ]
        question_context = f"Original question: {query_plan.original_query}"
        if query_plan.standalone_query != query_plan.original_query:
            question_context += f"\nStandalone question: {query_plan.standalone_query}"
        if is_first_message:
            question_context = (
                "【极重要指令】：请在最终回答第一行输出对话标题，格式为 "
                "[TITLE: 3-10字精炼标题]，然后换行回答。\n" + question_context
            )
        soul_directive = (
            f"\n\n【话题归属认知】:\n{soul_content[:600]}"
            if soul_content and soul_content.strip()
            else ""
        )
        messages = [
            {"role": "system", "content": (
                f"{SYSTEM_ROLE}\n\n{ANSWER_RULES}\n\n{soul_directive}\n\n"
                "Retrieval is complete. Do not call or describe tools. "
                "Answer only from the supplied evidence and include citation markers."
            )},
            *context_history,
            {"role": "user", "content": (
                f"{question_context}\nAnswer style: {query_plan.intent.value}\n\n"
                "Accepted evidence:\n[AUTHORITATIVE_EVIDENCE version=1]\n"
                f"{evidence_context}\n[/AUTHORITATIVE_EVIDENCE]"
            )},
        ]
        return messages, ordered_evidence

    @staticmethod
    def _prioritize_evidence(
        query: str,
        evidence: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        stopwords = {
            "which", "what", "how", "does", "the", "and", "from", "into",
            "with", "that", "this", "field", "module", "answer", "question",
            "request", "system", "use", "uses", "using", "performs",
        }

        def tokens(value: str) -> set[str]:
            expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
            return {
                token
                for token in re.findall(r"[a-z0-9]+", expanded.casefold().replace("_", " "))
                if len(token) >= 3 and token not in stopwords
            }

        query_tokens = tokens(query)
        ranked = []
        for index, item in enumerate(evidence):
            overlap = len(query_tokens & tokens(str(item.get("title") or "")))
            ranked.append((-overlap, index, item))
        ranked.sort(key=lambda entry: (entry[0], entry[1]))
        return [item for _, _, item in ranked]

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        query_plan: QueryPlan,
        retrieval_attempts: int,
        trace_id: str,
        preference: AnswerModelPreference = "auto",
    ) -> dict[str, Any]:
        complexity_reasons = answer_complexity_reasons(
            query_plan,
            retrieval_attempts=retrieval_attempts,
        )
        use_fast = self.fast_llm is not None and (
            preference == "fast"
            or (preference == "auto" and not complexity_reasons)
        )
        selected = self.fast_llm if use_fast else self.complex_llm
        logger.info(
            "[ANSWER_MODEL_ROUTE] trace_id=%s route=%s reasons=%s",
            trace_id,
            "fast" if use_fast else "complex",
            complexity_reasons or (["explicit_complex"] if preference == "complex" else ["single_target"]),
        )
        try:
            return selected.chat(messages, tools=None)
        except Exception as exc:
            if not use_fast:
                raise
            logger.warning(
                "[ANSWER_MODEL_FALLBACK] trace_id=%s error=%s",
                trace_id,
                exc.__class__.__name__,
            )
            return self.complex_llm.chat(messages, tools=None)
