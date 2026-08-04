import re
from dataclasses import dataclass
from typing import Tuple


_AMOUNT_OR_PERCENT = re.compile(
    r"(?:[$£€¥]\s?\d|\b\d[\d,.]*\s?"
    r"(?:%|percent\b|percentage\b|usd\b|gbp\b|eur\b|cny\b|rmb\b|元|万元|亿元))",
    re.IGNORECASE,
)
_CODE = re.compile(r"\b(?=\w*[A-Z])(?=\w*\d)[A-Z0-9][A-Z0-9._/-]{2,}\b")
_QUOTED = re.compile(r'''["“”‘’'][^"“”‘’']{2,}["“”‘’']''')
_IDENTIFIER = re.compile(r"\b[A-Z]{2,}(?:[-_/][A-Z0-9]+)*\b")


@dataclass(frozen=True)
class RouteDecision:
    selected_route: str
    retrievers: Tuple[str, ...]
    exact: bool


class QueryRouter:
    """Select retrieval channels with deterministic, latency-free rules."""

    def route(self, query: str, mode: str) -> RouteDecision:
        if mode == "vector":
            return RouteDecision("forced_vector", ("vector",), False)
        if mode == "bm25":
            return RouteDecision("forced_bm25", ("bm25",), False)

        exact = self.is_exact_query(query)
        if exact:
            return RouteDecision("hybrid_exact", ("vector", "bm25"), True)
        return RouteDecision("hybrid_semantic", ("vector",), False)

    @staticmethod
    def is_exact_query(query: str) -> bool:
        return any(
            pattern.search(query)
            for pattern in (_AMOUNT_OR_PERCENT, _CODE, _QUOTED, _IDENTIFIER)
        )
