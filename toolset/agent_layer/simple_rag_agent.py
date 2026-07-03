import logging
import re
import time
import uuid
from typing import Dict, List, Optional

from tool_layer import RetrievalError, RetrievalParameterError, SearchTool


logging.getLogger(__name__).addHandler(logging.NullHandler())


INSUFFICIENT_CONTEXT_MESSAGE = "当前知识库没有足够信息回答该问题"


class AgentError(Exception):
    """Raised when answer generation cannot complete."""


class ExtractiveAnswerGenerator:
    """Offline answer generator used for CP4 integration validation.

    The interface mirrors an LLM client: it receives a complete prompt and the
    retrieved context, then returns answer text. A real LLM adapter can replace
    this class without changing SimpleRagAgent.
    """

    def generate(self, prompt: str, query: str, contexts: List[Dict], trace_id: str) -> str:
        if not contexts:
            return INSUFFICIENT_CONTEXT_MESSAGE

        sentences = []
        for index, row in enumerate(contexts[:3], start=1):
            text = _first_sentence(row.get("chunk_text", ""))
            if text:
                sentences.append(f"{text} [{index}]")

        if not sentences:
            return INSUFFICIENT_CONTEXT_MESSAGE

        return " ".join(sentences)


class SimpleRagAgent:
    """Single-step RAG Agent for Q1 / CP4 acceptance."""

    def __init__(
        self,
        search_tool: Optional[SearchTool] = None,
        answer_generator=None,
        default_top_k: int = 5,
        default_mode: str = "hybrid",
        min_score: float = 0.0,
        logger: Optional[logging.Logger] = None,
    ):
        self.search_tool = search_tool or SearchTool()
        self.answer_generator = answer_generator or ExtractiveAnswerGenerator()
        self.default_top_k = default_top_k
        self.default_mode = default_mode
        self.min_score = min_score
        self.logger = logger or logging.getLogger(__name__)

    def answer(
        self,
        query: str,
        top_k: Optional[int] = None,
        mode: Optional[str] = None,
        filters: Optional[Dict] = None,
        min_score: Optional[float] = None,
        trace_id: Optional[str] = None,
    ) -> Dict:
        trace = trace_id or f"trace-{uuid.uuid4().hex[:12]}"
        started = time.perf_counter()
        query_text = "" if query is None else str(query).strip()
        top_k = self.default_top_k if top_k is None else top_k
        mode = mode or self.default_mode
        min_score = self.min_score if min_score is None else min_score

        if not query_text:
            self._log(trace, "invalid_query", started, "empty query")
            return {
                "trace_id": trace,
                "answer": "",
                "citations": [],
                "status": "invalid_query",
                "message": "query must not be empty",
            }

        try:
            retrieval_started = time.perf_counter()
            results = self.search_tool.search(
                query=query_text,
                top_k=top_k,
                mode=mode,
                filters=filters,
                min_score=min_score,
                trace_id=trace,
            )
            retrieval_latency_ms = int((time.perf_counter() - retrieval_started) * 1000)
            self.logger.info(
                "[AGENT_RETRIEVAL] trace_id=%s mode=%s results=%s latency=%sms top_score=%s",
                trace,
                mode,
                len(results),
                retrieval_latency_ms,
                _format_score(results[0]["score"]) if results else "-",
            )
        except RetrievalParameterError as exc:
            self._log(trace, "invalid_query", started, str(exc))
            return {
                "trace_id": trace,
                "answer": "",
                "citations": [],
                "status": "invalid_query",
                "message": str(exc),
            }
        except RetrievalError as exc:
            self._log(trace, "retrieval_error", started, str(exc))
            return {
                "trace_id": trace,
                "answer": "检索服务暂时不可用，请稍后重试",
                "citations": [],
                "status": "retrieval_error",
                "message": str(exc),
            }

        if not results:
            self._log(trace, "no_relevant_context", started, "no retrieval results")
            return {
                "trace_id": trace,
                "answer": INSUFFICIENT_CONTEXT_MESSAGE,
                "citations": [],
                "status": "no_relevant_context",
                "message": "retrieval returned no relevant context",
            }

        prompt = build_prompt(query_text, results)
        citations = _build_citations(results)

        try:
            llm_started = time.perf_counter()
            answer = self.answer_generator.generate(
                prompt=prompt,
                query=query_text,
                contexts=results,
                trace_id=trace,
            )
            llm_latency_ms = int((time.perf_counter() - llm_started) * 1000)
            if not str(answer).strip():
                raise AgentError("empty answer from generator")
            answer = _ensure_valid_citation(str(answer).strip(), citations)
            self.logger.info(
                "[AGENT_GENERATION] trace_id=%s latency=%sms citations=%s",
                trace,
                llm_latency_ms,
                len(citations),
            )
        except Exception as exc:
            self._log(trace, "llm_error", started, str(exc))
            return {
                "trace_id": trace,
                "answer": "模型服务暂时不可用，请稍后重试",
                "citations": citations,
                "status": "llm_error",
                "message": str(exc),
            }

        self._log(trace, "success", started, f"citations={len(citations)}")
        return {
            "trace_id": trace,
            "answer": answer,
            "citations": citations,
            "status": "success",
            "retrieval": {
                "mode": mode,
                "top_k": top_k,
                "result_count": len(results),
                "latency_ms": retrieval_latency_ms,
            },
        }

    def _log(self, trace_id: str, status: str, started: float, message: str) -> None:
        latency_ms = int((time.perf_counter() - started) * 1000)
        self.logger.info(
            "[AGENT] trace_id=%s status=%s latency=%sms message=%s",
            trace_id,
            status,
            latency_ms,
            message,
        )


def build_prompt(query: str, contexts: List[Dict]) -> str:
    context_blocks = []
    for index, row in enumerate(contexts, start=1):
        context_blocks.append(
            "\n".join(
                [
                    f"[{index}]",
                    f"title: {row.get('title', '')}",
                    f"url: {row.get('source_url', '')}",
                    f"doc_id: {row.get('doc_id', '')}",
                    f"chunk_id: {row.get('chunk_id', row.get('chunk_index', ''))}",
                    f"content: {row.get('chunk_text', '')}",
                ]
            )
        )

    return "\n\n".join(
        [
            "You are an enterprise knowledge-base QA assistant.",
            "Answer strictly from the retrieved context.",
            "Do not invent facts, numbers, owners, dates, workflows, or conclusions that are not present in the context.",
            f"If the context is insufficient, answer: {INSUFFICIENT_CONTEXT_MESSAGE}.",
            "Use citation markers such as [1] and [2] for every key claim.",
            f"user query: {query}",
            "retrieved context:",
            "\n\n".join(context_blocks),
            "final answer:",
        ]
    )


def _build_citations(results: List[Dict]) -> List[Dict]:
    citations = []
    for index, row in enumerate(results, start=1):
        citations.append(
            {
                "citation_id": index,
                "title": row.get("title", ""),
                "source_url": row.get("source_url", ""),
                "doc_id": row.get("doc_id", ""),
                "chunk_id": row.get("chunk_id", row.get("chunk_index", "")),
                "chunk_index": row.get("chunk_index"),
                "score": row.get("score", 0.0),
            }
        )
    return citations


def _ensure_valid_citation(answer: str, citations: List[Dict]) -> str:
    allowed = {str(item["citation_id"]) for item in citations}
    refs = set(re.findall(r"\[(\d+)\]", answer))
    invalid_refs = refs - allowed
    if invalid_refs:
        raise AgentError(f"answer contains invalid citations: {sorted(invalid_refs)}")
    if citations and not refs:
        return f"{answer} [1]"
    return answer


def _first_sentence(text: str, max_chars: int = 220) -> str:
    text = " ".join(str(text).split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _format_score(score) -> str:
    try:
        return f"{float(score):.4f}"
    except (TypeError, ValueError):
        return "-"
