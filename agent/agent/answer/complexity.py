import re

from agent.schemas.query_plan import QueryPlan


_MULTI_ASPECT_PATTERNS = (
    r"\bfrom\b.+\bto\b",
    r"\b(?:end[- ]to[- ]end|complete|full)\s+(?:flow|process|workflow|pipeline)\b",
    r"\bhow\b.+\band\b.+",
    r"从.+到.+(?:步骤|流程|链路)",
    r"(?:完整|整体|端到端).*(?:步骤|流程|链路|架构)",
    r"(?:哪些|所有).*(?:核心步骤|环节|阶段)",
    r"如何.+(?:并|以及|同时).+",
)


def answer_complexity_reasons(
    query_plan: QueryPlan,
    *,
    retrieval_attempts: int = 0,
) -> list[str]:
    """Derive answer complexity without changing the frozen QueryPlan contract."""

    reasons: list[str] = []
    if query_plan.intent.value in {"comparison", "summarization"}:
        reasons.append(f"intent:{query_plan.intent.value}")
    if query_plan.sub_queries:
        reasons.append("planned_sub_queries")
    if retrieval_attempts >= 2:
        reasons.append("corrective_retrieval")

    query = f"{query_plan.original_query}\n{query_plan.standalone_query}"
    if any(re.search(pattern, query, flags=re.IGNORECASE | re.DOTALL) for pattern in _MULTI_ASPECT_PATTERNS):
        reasons.append("multi_aspect_scope")
    return list(dict.fromkeys(reasons))


def requires_complex_answer(
    query_plan: QueryPlan,
    *,
    retrieval_attempts: int = 0,
) -> bool:
    return bool(
        answer_complexity_reasons(
            query_plan,
            retrieval_attempts=retrieval_attempts,
        )
    )
