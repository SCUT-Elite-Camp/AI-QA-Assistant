import json
import logging
from typing import Any

from pydantic import BaseModel, ValidationError

from agent.config.settings import settings
from agent.llm.base import BaseLLM
from agent.llm.llm_client import LLMClient
from agent.query.schemas import RewriteResult


class _ModelRewriteOutput(BaseModel):
    rewritten_query: str
    reason: str = ""


class QueryRewriter:
    """Rewrite a user query for retrieval without changing user intent."""

    def __init__(
        self,
        llm: BaseLLM | None = None,
        *,
        enabled: bool | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.llm = llm or LLMClient()
        self.enabled = (
            settings.QUERY_REWRITE_ENABLED if enabled is None else enabled
        )
        self.logger = logger or logging.getLogger("agent-layer.query")

    def rewrite(
        self,
        query: str,
        history: list[dict],
    ) -> RewriteResult:
        """Return a retrieval-oriented query, falling back safely on failure."""
        original_query = query
        normalized_query = query.strip()

        if not normalized_query:
            return self._unchanged(original_query, "empty_query")

        if not self.enabled:
            return self._unchanged(original_query, "query_rewrite_disabled")

        messages = [
            {
                "role": "system",
                "content": self._system_prompt(),
            },
            {
                "role": "user",
                "content": self._build_input(normalized_query, history),
            },
        ]

        try:
            response = self.llm.chat(messages)
            output = self._parse_response(response)
            rewritten_query = output.rewritten_query.strip()
            if not rewritten_query:
                raise ValueError("rewritten_query must not be empty")
        except Exception as exc:
            self.logger.warning(
                "[QUERY_REWRITE] action=fallback error=%s original_query=%s",
                exc.__class__.__name__,
                normalized_query,
            )
            return self._unchanged(original_query, "rewrite_failed")

        changed = rewritten_query != normalized_query
        result = RewriteResult(
            original_query=original_query,
            rewritten_query=rewritten_query,
            changed=changed,
            reason=output.reason,
        )
        self.logger.info(
            "[QUERY_REWRITE] changed=%s original_query=%s rewritten_query=%s",
            result.changed,
            normalized_query,
            result.rewritten_query,
        )
        return result

    @staticmethod
    def _system_prompt() -> str:
        return (
            "你是查询重写器。你的任务是结合对话历史，把当前问题改写为"
            "可以独立理解、适合知识库检索的问题。"
            "不得改变用户原始意图，不得添加历史中不存在的事实；"
            "必须保留模块名、接口名、代码标识符和专业术语。"
            "如果当前问题已经明确，保持原文。"
            "只返回 JSON，不要使用 Markdown。格式为："
            '{"rewritten_query":"...","reason":"..."}'
        )

    @staticmethod
    def _build_input(query: str, history: list[dict]) -> str:
        safe_history = QueryRewriter._normalize_history(history)
        return json.dumps(
            {
                "history": safe_history,
                "current_query": query,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _normalize_history(history: list[dict]) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for message in history or []:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            content = message.get("content")
            if role not in {"user", "assistant"} or not isinstance(content, str):
                continue
            normalized.append({"role": role, "content": content})
        return normalized

    @staticmethod
    def _parse_response(response: dict[str, Any]) -> _ModelRewriteOutput:
        content = response.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("LLM response content is empty")

        payload = QueryRewriter._extract_json_object(content.strip())
        try:
            return _ModelRewriteOutput.model_validate(payload)
        except ValidationError as exc:
            raise ValueError("LLM rewrite response is invalid") from exc

    @staticmethod
    def _extract_json_object(content: str) -> dict[str, Any]:
        if content.startswith("```") and content.endswith("```"):
            lines = content.splitlines()
            if len(lines) >= 3:
                content = "\n".join(lines[1:-1]).strip()

        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("LLM rewrite response is not valid JSON") from exc

        if not isinstance(payload, dict):
            raise ValueError("LLM rewrite response must be a JSON object")
        return payload

    @staticmethod
    def _unchanged(original_query: str, reason: str) -> RewriteResult:
        return RewriteResult(
            original_query=original_query,
            rewritten_query=original_query.strip(),
            changed=False,
            reason=reason,
        )
