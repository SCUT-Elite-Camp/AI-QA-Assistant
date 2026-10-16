"""Translate provider-specific thinking flags at the HTTP boundary."""

from urllib.parse import urlsplit

from agent.config.settings import settings


def is_openrouter(api_base: str) -> bool:
    return urlsplit(api_base).hostname == "openrouter.ai"


def is_groq(api_base: str) -> bool:
    return urlsplit(api_base).hostname == "api.groq.com"


def apply_provider_options(payload: dict, api_base: str) -> dict:
    if is_groq(api_base):
        result = dict(payload)
        enabled = result.pop('enable_thinking', None)
        thinking = result.pop('thinking', None)
        result.pop('thinking_budget', None)
        if str(result.get('model', '')).startswith('openai/gpt-oss-'):
            # GPT-OSS always reasons; Fast means low effort, not disabled.
            if enabled is None and isinstance(thinking, dict):
                enabled = thinking.get('type') == 'enabled'
            if enabled is None and result.get('model') == settings.ANSWER_FAST_MODEL:
                enabled = settings.ANSWER_FAST_MODEL_THINKING
            effort = 'low' if enabled is False else (settings.LLM_REASONING_EFFORT or 'high')
            result.setdefault('reasoning_effort', effort)
            result.pop('reasoning_format', None)
        if 'max_tokens' in result:
            result.setdefault('max_completion_tokens', result.pop('max_tokens'))
        return result
    if urlsplit(api_base).hostname == 'generativelanguage.googleapis.com':
        # These vendor extensions are rejected by Gemini's OpenAI endpoint.
        # Reasoning options, when explicitly configured, use its native schema.
        return {key: value for key, value in payload.items()
                if key not in {'enable_thinking', 'thinking', 'thinking_budget'}}
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
