import time
from importlib import import_module
from typing import Any, Optional

from agent.config.settings import settings
from agent.errors.exceptions import RetrievalError
from agent.logger.logger import get_logger
from agent.retrieval.base import BaseRetriever
from agent.retrieval.mock_retrieval import MockRetrieval
from agent.schemas.retrieval import RetrievalResult
from agent.trace.trace_id import get_trace_id

logger = get_logger(__name__)

SUPPORTED_RETRIEVAL_MODES = {"vector", "bm25", "hybrid"}


class RetrievalAdapter(BaseRetriever):
    """Adapter between Agent Layer and retrieval implementations."""

    def __init__(
        self,
        retriever: Any | None = None,
        use_mock: bool | None = None,
    ) -> None:
        if retriever is not None:
            self.retriever = retriever
            return

        should_use_mock = settings.USE_MOCK_RETRIEVAL if use_mock is None else use_mock
        self.retriever = MockRetrieval() if should_use_mock else None

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[dict] = None,
        mode: str = "hybrid",
        min_score: float = 0.0,
        trace_id: Optional[str] = None,
    ) -> list[RetrievalResult]:
        actual_trace_id = trace_id or get_trace_id() or "-"
        start_time = time.perf_counter()

        logger.info(
            "[RETRIEVAL_START] trace_id=%s query=%s top_k=%s mode=%s min_score=%s",
            actual_trace_id,
            query,
            top_k,
            mode,
            min_score,
        )

        try:
            if not query or not query.strip():
                raise RetrievalError("Query cannot be empty")

            if top_k < 1 or top_k > 20:
                raise RetrievalError("top_k must be between 1 and 20")

            if mode not in SUPPORTED_RETRIEVAL_MODES:
                raise RetrievalError(f"Unsupported retrieval mode: {mode}")

            if min_score < 0.0 or min_score > 1.0:
                raise RetrievalError("min_score must be between 0.0 and 1.0")

            raw_results = self._call_retriever(
                query=query,
                top_k=top_k,
                filters=filters,
                mode=mode,
                min_score=min_score,
                trace_id=actual_trace_id,
            ) or []

            normalized_results = [
                self._normalize_result(raw_result) for raw_result in raw_results
            ]

            final_results = [
                result for result in normalized_results if result.score >= min_score
            ][:top_k]

            latency_ms = int((time.perf_counter() - start_time) * 1000)

            logger.info(
                "[RETRIEVAL_END] trace_id=%s results_count=%s latency_ms=%s",
                actual_trace_id,
                len(final_results),
                latency_ms,
            )

            return final_results

        except RetrievalError as exc:
            latency_ms = int((time.perf_counter() - start_time) * 1000)

            logger.error(
                "[RETRIEVAL_ERROR] trace_id=%s latency_ms=%s error=%s",
                actual_trace_id,
                latency_ms,
                exc,
                exc_info=True,
            )

            raise

        except Exception as exc:
            latency_ms = int((time.perf_counter() - start_time) * 1000)

            logger.error(
                "[RETRIEVAL_ERROR] trace_id=%s latency_ms=%s error=%s",
                actual_trace_id,
                latency_ms,
                exc,
                exc_info=True,
            )

            raise RetrievalError(f"Retrieval service unavailable: {exc}") from exc

    def _load_search_tool(self) -> Any:
        try:
            module = import_module(settings.TOOL_LAYER_IMPORT)
            search_tool_class = getattr(module, settings.TOOL_LAYER_CLASS)
            return search_tool_class()
        except Exception as exc:
            raise RetrievalError(f"Tool layer initialization failed: {exc}") from exc

    def _call_retriever(
        self,
        query: str,
        top_k: int,
        filters: Optional[dict],
        mode: str,
        min_score: float,
        trace_id: Optional[str],
    ) -> list[Any]:
        retriever = self.retriever or self._load_search_tool()
        self.retriever = retriever

        if hasattr(retriever, "search"):
            return retriever.search(
                query=query,
                top_k=top_k,
                mode=mode,
                filters=filters,
                min_score=min_score,
                trace_id=trace_id,
            )

        if hasattr(retriever, "retrieve"):
            return retriever.retrieve(
                query=query,
                top_k=top_k,
                filters=filters,
                mode=mode,
                min_score=min_score,
                trace_id=trace_id,
            )

        raise RetrievalError("Retriever must provide search() or retrieve().")

    def _normalize_result(self, raw_result: Any) -> RetrievalResult:
        if isinstance(raw_result, RetrievalResult):
            return raw_result

        if isinstance(raw_result, dict):
            return self._normalize_mapping(raw_result)

        return self._normalize_mapping(
            {
                "doc_id": getattr(raw_result, "doc_id", ""),
                "chunk_id": getattr(raw_result, "chunk_id", None),
                "chunk_index": getattr(raw_result, "chunk_index", None),
                "chunk_text": getattr(raw_result, "chunk_text", ""),
                "title": getattr(raw_result, "title", ""),
                "source_url": getattr(raw_result, "source_url", ""),
                "score": getattr(raw_result, "score", 0.0),
            }
        )

    def _normalize_mapping(self, data: dict[str, Any]) -> RetrievalResult:
        doc_id = str(data.get("doc_id") or "")
        chunk_index = data.get("chunk_index")
        if chunk_index is None:
            chunk_index = 0

        chunk_id = data.get("chunk_id") or f"{doc_id}::chunk_{chunk_index}"
        chunk_text = data.get("chunk_text") or data.get("content") or data.get("text") or ""
        title = data.get("title") or doc_id
        source_url = data.get("source_url") or ""
        score = float(data.get("score") or 0.0)

        return RetrievalResult(
            doc_id=doc_id,
            chunk_id=str(chunk_id),
            chunk_index=int(chunk_index),
            chunk_text=str(chunk_text),
            title=str(title),
            source_url=str(source_url),
            score=score,
        )
