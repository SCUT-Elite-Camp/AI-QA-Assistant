from typing import Optional

from agent.retrieval.base import BaseRetriever
from agent.schemas.retrieval import RetrievalResult


class MockRetrieval(BaseRetriever):
    """Mock retriever for local development and testing."""

    def __init__(self, return_empty: bool = False, should_raise: bool = False) -> None:
        self.return_empty = return_empty
        self.should_raise = should_raise

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[dict] = None,
        mode: str = "hybrid",
        min_score: float = 0.0,
        trace_id: Optional[str] = None,
    ) -> list[RetrievalResult]:
        _ = (query, filters, mode, trace_id)

        if self.should_raise:
            raise RuntimeError("mock retrieval error")

        if self.return_empty:
            return []

        results = [
            RetrievalResult(
                doc_id="agent-q1-plan",
                chunk_id="agent-q1-plan::chunk_0",
                chunk_index=0,
                title="Agent Layer Q1 Scope",
                source_url="",
                score=0.96,
                chunk_text=(
                    "Q1 implements a simplified single-turn RAG Agent. "
                    "The Agent receives a user query, calls retrieval once, "
                    "builds a prompt, calls the LLM, and returns an answer with citations."
                ),
            ),
            RetrievalResult(
                doc_id="agent-interface-contract",
                chunk_id="agent-interface-contract::chunk_0",
                chunk_index=0,
                title="Web-Agent Interface Contract",
                source_url="",
                score=0.91,
                chunk_text=(
                    "The /api/chat endpoint returns trace_id, status, answer, "
                    "message, and citations. The frontend uses these fields for display."
                ),
            ),
            RetrievalResult(
                doc_id="agent-work-division",
                chunk_id="agent-work-division::chunk_0",
                chunk_index=0,
                title="Team Collaboration Division",
                source_url="",
                score=0.88,
                chunk_text=(
                    "xdj is responsible for the main Agent workflow. "
                    "lhf is responsible for infrastructure, retrieval adapter, "
                    "logging, tracing, configuration, errors, and tests."
                ),
            ),
        ]

        return [result for result in results if result.score >= min_score][:top_k]
