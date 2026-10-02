"""Deterministic required-fact matching used by completeness gating and repair guards."""

from __future__ import annotations

import re
import unicodedata


_VOWELS = set("aeiou")


def safe_ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def normalized_fact_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[^\w\u3400-\u9fff]+", "", value, flags=re.UNICODE)


def identifier_tokens(text: str) -> set[str]:
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    expanded = unicodedata.normalize("NFKC", expanded).casefold().replace("_", " ")
    return {
        token
        for token in re.findall(r"[a-z0-9]+", expanded)
        if len(token) >= 2
    }


def english_inflection_variants(token: str) -> set[str]:
    """Conservative singular/plural variants for one English token."""

    token = token.casefold()
    variants = {token}
    if len(token) < 3:
        return variants

    if token.endswith("ies") and len(token) > 4:
        variants.add(token[:-3] + "y")
    if token.endswith(("ses", "xes", "zes")) and len(token) > 4:
        variants.add(token[:-2])
    if token.endswith(("ches", "shes")) and len(token) > 5:
        variants.add(token[:-2])
    if token.endswith("es") and len(token) > 4:
        variants.add(token[:-2])
    if token.endswith("s") and not token.endswith("ss") and len(token) > 3:
        variants.add(token[:-1])

    if token.endswith("y") and len(token) > 2 and token[-2] not in _VOWELS:
        variants.add(token[:-1] + "ies")
    else:
        variants.add(token + "s")
        variants.add(token + "es")
    return {item for item in variants if len(item) >= 3}


def _normalized_inflection_variants(text: str) -> set[str]:
    base = normalized_fact_text(text)
    variants = {base}
    if not base:
        return variants
    if base.endswith("ies") and len(base) > 4:
        variants.add(base[:-3] + "y")
    if base.endswith("es") and len(base) > 4:
        variants.add(base[:-2])
    if base.endswith("s") and not base.endswith("ss") and len(base) > 3:
        variants.add(base[:-1])
    if base.endswith("y") and len(base) > 2:
        variants.add(base[:-1] + "ies")
    else:
        variants.add(base + "s")
        variants.add(base + "es")
    return {item for item in variants if len(item) >= 3}


def _tokens_equivalent(left: str, right: str) -> bool:
    return bool(english_inflection_variants(left) & english_inflection_variants(right))


def _token_set_covered(term_tokens: set[str], answer_tokens: set[str]) -> bool:
    if len(term_tokens) < 2:
        return False
    for term_token in term_tokens:
        if not any(_tokens_equivalent(term_token, answer_token) for answer_token in answer_tokens):
            return False
    return True


def required_fact_match_details(
    answer: str,
    fact_groups: list[list[str]],
) -> list[dict[str, str | bool | None]]:
    """Return deterministic alias/identifier matches, including inflection."""

    normalized_answer = normalized_fact_text(answer)
    answer_tokens = identifier_tokens(answer)
    details: list[dict[str, str | bool | None]] = []
    for group in fact_groups:
        detail: dict[str, str | bool | None] = {
            "hit": False,
            "matched_term": None,
            "match_type": None,
        }
        for term in group:
            normalized_term = normalized_fact_text(term)
            if normalized_term and normalized_term in normalized_answer:
                detail.update(hit=True, matched_term=term, match_type="normalized_alias")
                break
            if any(
                variant in normalized_answer
                for variant in _normalized_inflection_variants(term)
                if len(variant) >= 4 or variant.isdigit()
            ):
                detail.update(hit=True, matched_term=term, match_type="inflection")
                break
            term_tokens = identifier_tokens(term)
            if _token_set_covered(term_tokens, answer_tokens):
                detail.update(hit=True, matched_term=term, match_type="identifier_tokens")
                break
        details.append(detail)
    return details


def required_fact_coverage(answer: str, fact_groups: list[list[str]]) -> tuple[float, list[bool]]:
    details = required_fact_match_details(answer, fact_groups)
    hits = [bool(detail["hit"]) for detail in details]
    return safe_ratio(sum(hits), len(hits)), hits


def missing_targets(answer: str, targets: list[str]) -> list[str]:
    if not targets:
        return []
    _, hits = required_fact_coverage(answer, [[target] for target in targets])
    return [target for target, hit in zip(targets, hits) if not hit]


def numeric_atoms(text: str) -> set[str]:
    return {item.replace(",", "") for item in re.findall(r"\d+(?:\.\d+)?%?", text)}


def should_accept_repair(
    original: str,
    repaired: str,
    targets: list[str],
) -> tuple[bool, str]:
    """Reject empty rewrites, coverage drops, and dropped numeric atoms."""

    if not repaired.strip():
        return False, "empty_repair"
    groups = [[target] for target in targets] if targets else []
    before = required_fact_coverage(original, groups)[0] if groups else 1.0
    after = required_fact_coverage(repaired, groups)[0] if groups else 1.0
    if after + 1e-12 < before:
        return False, "coverage_dropped"
    lost_numbers = numeric_atoms(original) - numeric_atoms(repaired)
    if lost_numbers:
        return False, "lost_numeric_atoms"
    return True, "accepted"
