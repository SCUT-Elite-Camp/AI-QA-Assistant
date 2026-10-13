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
                "On the first line output a concise English chat title as "
                "[TITLE: 2-6 word title], then answer on a new line.\n" + question_context
            )
        soul_directive = (
            "\n\n[VERIFIED_TOPIC_MEMORY]\n"
            f"{soul_content[:600]}\n"
            "[/VERIFIED_TOPIC_MEMORY]\n"
            "For questions about facts remembered in this Topic, this verified memory "
            "is usable context. Answer directly from it when it contains the requested fact; "
            "do not claim the fact is absent merely because retrieved documents omit it. "
            "Do not attach document citation markers to a fact supported only by Topic memory."
            if soul_content and soul_content.strip()
            else ""
        )
        messages = [
            {"role": "system", "content": (
                f"{SYSTEM_ROLE}\n\n{ANSWER_RULES}\n\n{soul_directive}\n\n"
                "Retrieval is complete. Do not call or describe tools. "
                "Answer from the accepted document evidence or verified Topic memory. "
                "Use citation markers for claims grounded in numbered document evidence."
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
        # English is the product default, regardless of source/history language.
        # Copy the prompt so caller history remains immutable.
        instruction = "Write the entire answer in English unless the user explicitly requests another output language. Preserve technical identifiers and citation markers. Do not change language because prior conversation or sources use another language."
        messages = [dict(message) for message in messages]
        if messages and messages[0].get('role') == 'system':
            messages[0]['content'] = str(messages[0].get('content', '')) + '\n\n' + instruction
        else:
            messages.insert(0, {'role': 'system', 'content': instruction})
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
            from agent.streaming.live import CURRENT_STREAM_SINK, emit_model_event
            if CURRENT_STREAM_SINK.get() is not None:
                emit_model_event("answer-start", {})
                content = []
                for delta in selected.stream_chat(messages, tools=None):
                    if delta.get("reasoning_content"):
                        emit_model_event("reasoning", {"content": delta["reasoning_content"]})
                    if delta.get("content"):
                        content.append(delta["content"])
                        emit_model_event("token", {"content": delta["content"]})
                return {"role": "assistant", "content": "".join(content)}
            return selected.chat(messages, tools=None)
        except Exception as exc:
            # A second model must never splice its answer into a partial stream.
            from agent.streaming.live import CURRENT_STREAM_SINK
            if CURRENT_STREAM_SINK.get() is not None:
                raise
            if not use_fast:
                raise
            logger.warning(
                "[ANSWER_MODEL_FALLBACK] trace_id=%s error=%s",
                trace_id,
                exc.__class__.__name__,
            )
            return self.complex_llm.chat(messages, tools=None)
