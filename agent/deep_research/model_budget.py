"""Job-local completion budgets and bounded, permission-aware model transport."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import RLock
from typing import Callable
import logging
import math
import os
import re
import time
from typing import Iterator

import requests

from agent.config.settings import settings
from .access import check_research_model_access

logger = logging.getLogger(__name__)


class ResearchTokenBudgetExceeded(RuntimeError):
    pass


@dataclass
class CompletionBudget:
    limit: int
    spent: int = 0
    reserve_hook: Callable[[int], str] | None = None
    settle_hook: Callable[[str, int], None] | None = None
    lock: RLock = field(default_factory=RLock, repr=False)

    def reserve(self, tokens: int) -> str | None:
        with self.lock:
            if tokens > self.limit - self.spent:
                raise ResearchTokenBudgetExceeded("research_completion_budget_exceeded")
            reservation = self.reserve_hook(tokens) if self.reserve_hook else None
            self.spent += tokens
            return reservation

    def settle(self, reservation: str | None, cap: int, used: int) -> None:
        with self.lock:
            if self.settle_hook and reservation:
                self.settle_hook(reservation, used)
            self.spent += used - cap


_BUDGET: ContextVar[CompletionBudget | None] = ContextVar("research_completion_budget", default=None)


@contextmanager
def completion_budget_scope(limit: int | None = None, *, spent: int = 0, reserve_hook=None, settle_hook=None) -> Iterator[CompletionBudget]:
    # A renderer may be nested in the approved runtime budget; never reset it.
    current = _BUDGET.get()
    if current is not None:
        yield current
        return
    budget = CompletionBudget(min(limit or settings.RESEARCH_MODEL_TOTAL_TOKENS,
                                  settings.RESEARCH_MODEL_TOTAL_TOKENS), spent, reserve_hook, settle_hook)
    token = _BUDGET.set(budget)
    try:
        yield budget
    finally:
        _BUDGET.reset(token)


def with_completion_budget(payload: dict, *, model: str) -> dict:
    """Reserve reasoning in addition to visible output; the provider cap covers both."""
    result = dict(payload)
    result["messages"] = [dict(m) for m in payload.get("messages", [])]
    output = min(int(result.pop("max_completion_tokens", result.get("max_tokens", 2048))),
                 settings.RESEARCH_MODEL_OUTPUT_TOKENS)
    thinking = result.get("enable_thinking")
    if thinking is None:
        thinking = (result.get("thinking") or {}).get("type", settings.LLM_THINKING_MODE) == "enabled"
    reasoning = settings.RESEARCH_MODEL_REASONING_TOKENS if thinking or model.startswith("openai/gpt-oss-") else 0
    result["max_tokens"] = output + reasoning
    instruction = (f"Completion budget: {output + reasoning} tokens including reasoning and final output. "
                   f"Aim to finish reasoning within {reasoning} tokens and reserve up to {output} tokens "
                   "for the requested final output. Return the final output before the budget is exhausted. "
                   "These are planning targets; do not mention the budget in the answer.")
    if result["messages"] and result["messages"][0].get("role") == "system":
        result["messages"][0]["content"] = str(result["messages"][0].get("content", "")) + "\n" + instruction
    else:
        result["messages"].insert(0, {"role": "system", "content": instruction})
    return result


def _retry_delay(response) -> float | None:
    value = getattr(response, "headers", {}).get("Retry-After")
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        match = re.search(r"try again in\s+(\d+(?:\.\d+)?)s", str(getattr(response, "text", "")), re.I)
        seconds = float(match.group(1)) if match else 1.0
    if not math.isfinite(seconds) or seconds < 0 or seconds > settings.RESEARCH_MODEL_MAX_RETRY_WAIT_SECONDS:
        return None
    return min(seconds + 0.25, settings.RESEARCH_MODEL_MAX_RETRY_WAIT_SECONDS)


def post_completion(api_base: str, api_key: str, payload: dict, timeout: float) -> dict:
    """Two attempts at most. Reserve failed/unknown usage; reconcile successful usage."""
    with completion_budget_scope() as budget, requests.Session() as session:
        proxy = os.getenv("LLM_HTTP_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
        if proxy:
            session.proxies.update({"http": proxy, "https": proxy})
        cap = int(payload.get("max_completion_tokens", payload.get("max_tokens", 2048)))
        for attempt in range(2):
            check_research_model_access()
            reservation = budget.reserve(cap)
            logger.info("Research model request model=%s completion_cap=%d budget_remaining=%d attempt=%d",
                        payload.get("model"), cap, budget.limit - budget.spent, attempt + 1)
            try:
                response = session.post(api_base.rstrip("/") + "/chat/completions", json=payload,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    timeout=timeout)
            except requests.HTTPError as exc:
                _log_rejection(exc.response, api_key)
                raise
            except requests.RequestException:
                if attempt:
                    raise
                check_research_model_access()
                time.sleep(0.5)
                continue
            if getattr(response, "status_code", 200) == 413:
                budget.settle(reservation, cap, 0)
            if getattr(response, "status_code", 200) == 429:
                # Rejected requests have no completion. Keep other unknown failures reserved.
                budget.settle(reservation, cap, 0)
                delay = _retry_delay(response)
                if attempt == 0 and delay is not None:
                    logger.warning("Research model rate limited; waiting %.2fs before one retry", delay)
                    check_research_model_access()
                    time.sleep(delay)
                    continue
            try:
                response.raise_for_status()
            except requests.HTTPError:
                _log_rejection(response, api_key)
                raise
            result = response.json()
            usage = result.get("usage") or {}
            used = usage.get("completion_tokens")
            if type(used) is int and used >= 0:
                budget.settle(reservation, cap, used)
            choice = next(iter(result.get("choices", [])), {})
            logger.info("Research model response model=%s completion_tokens=%s reasoning_tokens=%s finish_reason=%s budget_spent=%d",
                        payload.get("model"), used, (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
                        choice.get("finish_reason"), budget.spent)
            check_research_model_access()
            return result
        raise RuntimeError("research_model_transport_exhausted")


def _log_rejection(response, api_key: str) -> None:
    if response is None:
        return
    try:
        body = response.json()
        if isinstance(body, list):
            body = next((item for item in body if isinstance(item, dict)), {})
        error = body.get("error", {}) if isinstance(body, dict) else {}
        if not isinstance(error, dict):
            error = {}
        message = str(error.get("message", ""))
        if api_key:
            message = message.replace(api_key, "[redacted]")
        logger.warning("Research model HTTP %s (%s): %s", response.status_code, error.get("code"), message[:300])
    except (ValueError, TypeError):
        pass
