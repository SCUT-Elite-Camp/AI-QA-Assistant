"""Translate provider-specific thinking flags at the HTTP boundary."""

from urllib.parse import urlsplit

from agent.config.settings import settings


def is_openrouter(api_base: str) -> bool:
    return urlsplit(api_base).hostname == "openrouter.ai"


def apply_provider_options(payload: dict, api_base: str) -> dict:
    if not is_openrouter(api_base):
        return payload

    result = dict(payload)
    enabled = result.pop("enable_thinking", None)
    thinking = result.pop("thinking", None)
    result.pop("thinking_budget", None)
    if enabled is None and isinstance(thinking, dict):
        enabled = thinking.get("type") == "enabled"
    if enabled is None and settings.LLM_THINKING_MODE in {"enabled", "disabled"}:
        enabled = settings.LLM_THINKING_MODE == "enabled"
    if enabled is not None:
        reasoning = dict(result.get("reasoning") or {})
        reasoning["enabled"] = bool(enabled)
        if enabled:
            if settings.LLM_REASONING_EFFORT:
                reasoning.setdefault("effort", settings.LLM_REASONING_EFFORT)
            # OpenRouter counts reasoning and visible output in the same budget.
            result["max_tokens"] = max(int(result.get("max_tokens", 2000)), 4096)
        else:
            reasoning.pop("effort", None)
            reasoning.pop("max_tokens", None)
        result["reasoning"] = reasoning
    return result
