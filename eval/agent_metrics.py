"""Pure metrics used by the CP2 Agent evaluation suite."""

from __future__ import annotations

import math
import re
import unicodedata
from statistics import mean
from typing import Iterable


def safe_ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def binary_scores(expected: Iterable[bool], predicted: Iterable[bool]) -> dict[str, float | int]:
    pairs = list(zip(expected, predicted))
    tp = sum(1 for truth, guess in pairs if truth and guess)
    fp = sum(1 for truth, guess in pairs if not truth and guess)
    fn = sum(1 for truth, guess in pairs if truth and not guess)
    tn = sum(1 for truth, guess in pairs if not truth and not guess)
    precision = safe_ratio(tp, tp + fp)
    recall = safe_ratio(tp, tp + fn)
    return {
        "precision": precision,
        "recall": recall,
        "f1": safe_ratio(2 * precision * recall, precision + recall),
        "accuracy": safe_ratio(tp + tn, len(pairs)),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }


def percentile(values: Iterable[float], p: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p / 100.0
    low, high = math.floor(rank), math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def latency_summary(values: Iterable[float]) -> dict[str, float | int]:
    samples = list(values)
    return {
        "count": len(samples),
        "mean_ms": round(mean(samples), 2) if samples else 0.0,
        "min_ms": round(min(samples), 2) if samples else 0.0,
        "p50_ms": round(percentile(samples, 50), 2),
        "p90_ms": round(percentile(samples, 90), 2),
        "p95_ms": round(percentile(samples, 95), 2),
        "max_ms": round(max(samples), 2) if samples else 0.0,
    }


def _normalized_fact_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[^\w\u3400-\u9fff]+", "", value, flags=re.UNICODE)


def _identifier_tokens(text: str) -> set[str]:
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    expanded = unicodedata.normalize("NFKC", expanded).casefold().replace("_", " ")
    return {
        token
        for token in re.findall(r"[a-z0-9]+", expanded)
        if len(token) >= 2
    }


def required_fact_match_details(
    answer: str,
    fact_groups: list[list[str]],
) -> list[dict[str, str | bool | None]]:
    """Return deterministic and explainable alias/identifier matches."""

    normalized_answer = _normalized_fact_text(answer)
    answer_tokens = _identifier_tokens(answer)
    details: list[dict[str, str | bool | None]] = []
    for group in fact_groups:
        detail: dict[str, str | bool | None] = {
            "hit": False,
            "matched_term": None,
            "match_type": None,
        }
        for term in group:
            normalized_term = _normalized_fact_text(term)
            if normalized_term and normalized_term in normalized_answer:
                detail.update(hit=True, matched_term=term, match_type="normalized_alias")
                break
            term_tokens = _identifier_tokens(term)
            if len(term_tokens) >= 2 and term_tokens.issubset(answer_tokens):
                detail.update(hit=True, matched_term=term, match_type="identifier_tokens")
                break
        details.append(detail)
    return details


def required_fact_coverage(answer: str, fact_groups: list[list[str]]) -> tuple[float, list[bool]]:
    details = required_fact_match_details(answer, fact_groups)
    hits = [bool(detail["hit"]) for detail in details]
    return safe_ratio(sum(hits), len(hits)), hits


def required_term_recall(text: str, terms: list[str]) -> float:
    if not terms:
        return 1.0
    normalized = text.casefold()
    return safe_ratio(sum(term.casefold() in normalized for term in terms), len(terms))


def normalize_answer(text: str) -> str:
    """Normalize formatting differences common in financial answers."""
    value = unicodedata.normalize("NFKC", text).casefold()
    value = value.replace(",", "")
    return re.sub(r"[^a-z0-9.%+-]+", " ", value).strip()


def reference_answer_match(answer: str, reference: str) -> bool:
    """Accept the gold answer as a normalized span of the generated answer."""
    normalized_answer = normalize_answer(answer)
    normalized_reference = normalize_answer(reference)
    return bool(normalized_reference and normalized_reference in normalized_answer)


def reference_token_f1(answer: str, reference: str) -> float:
    """Token-overlap F1 for paraphrases; exact match remains a separate metric."""
    answer_tokens = _meaningful_tokens(answer)
    reference_tokens = _meaningful_tokens(reference)
    if not answer_tokens or not reference_tokens:
        return 0.0
    overlap = len(answer_tokens & reference_tokens)
    precision = overlap / len(answer_tokens)
    recall = overlap / len(reference_tokens)
    return safe_ratio(2 * precision * recall, precision + recall)


def reference_token_recall(answer: str, reference: str) -> float:
    answer_tokens = _meaningful_tokens(answer)
    reference_tokens = _meaningful_tokens(reference)
    return safe_ratio(len(answer_tokens & reference_tokens), len(reference_tokens))


def reference_quality_pass(answer: str, reference: str, recall_threshold: float = 0.3) -> bool:
    """Require semantic token coverage and preservation of financial numbers."""
    if reference_answer_match(answer, reference):
        return True
    normalized_answer = normalize_answer(answer)
    reference_numbers = {token for token in normalize_answer(reference).split() if any(ch.isdigit() for ch in token)}
    if any(number not in normalized_answer for number in reference_numbers):
        return False
    return reference_token_recall(answer, reference) >= recall_threshold


def _meaningful_tokens(text: str) -> set[str]:
    stopwords = {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "in", "is", "it", "of", "on", "or", "that", "the", "there", "to",
        "was", "were", "with", "various",
    }
    return {token for token in normalize_answer(text).split() if token not in stopwords}


def expected_document_hit(citations: list[dict], expected_doc_names: list[str]) -> bool:
    if not expected_doc_names:
        return True
    citation_text = " ".join(
        str(citation.get(field) or "")
        for citation in citations
        for field in ("title", "doc_id", "source_url")
    ).casefold()
    return any(name.casefold() in citation_text for name in expected_doc_names)
