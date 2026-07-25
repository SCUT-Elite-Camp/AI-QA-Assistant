import json
import logging
from typing import Any

from pydantic import ValidationError

from agent.config.settings import settings
from agent.llm.base import BaseLLM
from agent.llm.llm_client import LLMClient
from agent.query.schemas import ClarificationDecision


class Clarifier:
    """Decide whether a query needs user clarification before retrieval."""

    def __init__(
        self,
        llm: BaseLLM | None = None,
        *,
        enabled: bool | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.llm = llm or LLMClient()
        self.enabled = (
            settings.CLARIFICATION_ENABLED if enabled is None else enabled
        )
        self.logger = logger or logging.getLogger("agent-layer.query")

    def evaluate(
        self,
        query: str,
        history: list[dict],
    ) -> ClarificationDecision:
        """Return a structured decision, defaulting to continue on failure."""
        normalized_query = query.strip()

        if not normalized_query:
            return self._continue("empty_query")

        if not self.enabled:
            return self._continue("clarification_disabled")

        messages = [
            {"role": "system", "content": self._system_prompt()},
            {
                "role": "user",
                "content": self._build_input(normalized_query, history),
            },
        ]

        try:
            response = self.llm.chat(messages)
            decision = self._parse_response(response)
            decision.question = decision.question.strip()
            decision.reason = decision.reason.strip()
            if decision.needs_clarification and not decision.question:
                raise ValueError("clarification question must not be empty")
            if not decision.needs_clarification:
                decision.question = ""
        except Exception as exc:
            self.logger.warning(
                "[CLARIFICATION] action=fallback error=%s query=%s",
                exc.__class__.__name__,
                normalized_query,
            )
            return self._continue("clarification_check_failed")

        self.logger.info(
            "[CLARIFICATION] needs_clarification=%s query=%s reason=%s",
            decision.needs_clarification,
            normalized_query,
            decision.reason,
        )
        return decision

    @staticmethod
    def _system_prompt() -> str:
        return (
            "你是用户意图澄清判断器。请结合会话历史判断当前问题是否必须"
            "先向用户澄清，才能安全检索或回答。仅在无法从历史确定指代、"
            "问题缺少主题、存在多个明显不同的业务对象，或缺少必需范围条件时"
            "要求澄清。问题虽短但含义明确、历史能够消除指代、或查询重写即可"
            "解决时，不要澄清。澄清问题必须具体且只询问解决歧义所需的信息。"
            "只返回 JSON，不要使用 Markdown。格式为："
            '{"needs_clarification":true,"question":"...","reason":"..."}'
        )

    @staticmethod
    def _build_input(query: str, history: list[dict]) -> str:
        return json.dumps(
            {
                "history": Clarifier._normalize_history(history),
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
    def _parse_response(response: dict[str, Any]) -> ClarificationDecision:
        content = response.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("LLM response content is empty")

        payload = Clarifier._extract_json_object(content.strip())
        try:
            return ClarificationDecision.model_validate(payload)
        except ValidationError as exc:
            raise ValueError("LLM clarification response is invalid") from exc

    @staticmethod
    def _extract_json_object(content: str) -> dict[str, Any]:
        if content.startswith("```") and content.endswith("```"):
            lines = content.splitlines()
            if len(lines) >= 3:
                content = "\n".join(lines[1:-1]).strip()

        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("LLM clarification response is not valid JSON") from exc

        if not isinstance(payload, dict):
            raise ValueError("LLM clarification response must be a JSON object")
        return payload

    @staticmethod
    def _continue(reason: str) -> ClarificationDecision:
        return ClarificationDecision(
            needs_clarification=False,
            question="",
            reason=reason,
        )
