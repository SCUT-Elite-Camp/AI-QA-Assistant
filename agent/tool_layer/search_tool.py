import time
from typing import Optional


class RetrievalError(Exception):
    """Raised when retrieval backend fails."""


class RetrievalParameterError(RetrievalError):
    """Raised when retrieval parameters are invalid."""


class SearchTool:
    """Temporary Tool Layer stub for Agent Layer real-mode smoke testing."""

    SUPPORTED_MODES = {"vector", "bm25", "hybrid"}

    def search(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "hybrid",
        filters: Optional[dict] = None,
        min_score: float = 0.0,
        trace_id: Optional[str] = None,
    ) -> list[dict]:
        start_time = time.time()

        self._validate_params(
            query=query,
            top_k=top_k,
            mode=mode,
            min_score=min_score,
        )

        results = [
            {
                "doc_id": "doc_001",
                "chunk_id": "doc_001::chunk_0",
                "chunk_index": 0,
                "chunk_text": (
                    "Q1 focuses on a single-turn RAG Agent flow. "
                    "The Agent Layer receives a user query, calls retrieval once, "
                    "builds a prompt, calls the LLM, and returns an answer with citations."
                ),
                "title": "Q1 Project Goals",
                "score": 0.92,
                "source_url": "",
            },
            {
                "doc_id": "doc_002",
                "chunk_id": "doc_002::chunk_0",
                "chunk_index": 0,
                "chunk_text": (
                    "The Tool Layer CP1 interface exposes SearchTool.search with "
                    "query, top_k, mode, filters, min_score, and trace_id parameters."
                ),
                "title": "Tool Layer CP1 Interface",
                "score": 0.87,
                "source_url": "",
            },
            {
                "doc_id": "doc_003",
                "chunk_id": "doc_003::chunk_0",
                "chunk_index": 0,
                "chunk_text": (
                    "Retrieval results should include doc_id, chunk_id, chunk_index, "
                    "chunk_text, title, score, and source_url."
                ),
                "title": "Retrieval Result Schema",
                "score": 0.82,
                "source_url": "",
            },
        ]

        filtered_results = [item for item in results if item["score"] >= min_score][:top_k]
        latency_ms = int((time.time() - start_time) * 1000)

        print(
            f"[RETRIEVAL] trace_id={trace_id} "
            f"mode={mode} top_k={top_k} "
            f"results={len(filtered_results)} latency={latency_ms}ms"
        )

        return filtered_results

    def _validate_params(
        self,
        query: str,
        top_k: int,
        mode: str,
        min_score: float,
    ) -> None:
        if not query or not query.strip():
            raise RetrievalParameterError("query must not be empty")

        if top_k < 1 or top_k > 20:
            raise RetrievalParameterError("top_k must be between 1 and 20")

        if mode not in self.SUPPORTED_MODES:
            raise RetrievalParameterError(f"mode must be one of {sorted(self.SUPPORTED_MODES)}")

        if min_score < 0.0 or min_score > 1.0:
            raise RetrievalParameterError("min_score must be between 0.0 and 1.0")
