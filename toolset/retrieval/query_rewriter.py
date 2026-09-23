import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Tuple


logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def contains_cjk(text: str) -> bool:
    """Return whether a query contains a CJK unified ideograph."""
    return bool(_CJK_PATTERN.search(text or ""))


@dataclass(frozen=True)
class RewriteConfig:
    api_base: Optional[str]
    api_key: Optional[str]
    model: Optional[str]
    timeout_ms: int = 1200
    max_variants: int = 2
    max_query_chars: int = 512
    cross_language_enabled: bool = False


class QueryRewriter(ABC):
    """Produce retrieval variants without owning the original query."""

    @abstractmethod
    def rewrite(self, query: str, max_variants: int = 2) -> List[str]:
        """Return zero or more validated variants and fail open on errors."""


class OpenAICompatibleQueryRewriter(QueryRewriter):
    """Call an OpenAI-compatible chat completion endpoint for query variants."""

    def __init__(
        self,
        config: RewriteConfig,
        request_client=None,
        request_logger: Optional[logging.Logger] = None,
    ) -> None:
        self.config = config
        self.request_client = request_client
        self.logger = request_logger or logger

    def rewrite(self, query: str, max_variants: int = 2) -> List[str]:
        variants, _ = self.rewrite_with_status(query, max_variants)
        return variants

    def rewrite_with_status(
        self,
        query: str,
        max_variants: int = 2,
    ) -> Tuple[List[str], str]:
        return self._rewrite_with_status(query, max_variants, None)

    def rewrite_with_context(
        self,
        query: str,
        max_variants: int,
        cross_language: bool,
    ) -> Tuple[List[str], str]:
        """Rewrite with an orchestrator-selected cross-language route."""
        return self._rewrite_with_status(query, max_variants, cross_language)

    def _rewrite_with_status(
        self,
        query: str,
        max_variants: int,
        cross_language_override: bool | None,
    ) -> Tuple[List[str], str]:
        if not self.config.api_base or not self.config.model:
            self.logger.error(
                "[QUERY_REWRITE_CONFIG_ERROR] api_base_configured=%s model_configured=%s",
                bool(self.config.api_base),
                bool(self.config.model),
            )
            return [], "config_error"

        cross_language = (
            self.config.cross_language_enabled and contains_cjk(query)
            if cross_language_override is None
            else bool(cross_language_override and contains_cjk(query))
        )
        limit = min(max(int(max_variants), 0), self.config.max_variants, 2)
        if cross_language:
            limit = min(limit, 1)
        if limit == 0:
            return [], "disabled"

        if cross_language:
            system_prompt = (
                "Translate the Chinese or mixed Chinese-English user query into one "
                "concise English retrieval query for an English BM25 index. Preserve "
                "the exact intent, product names, API names, code identifiers, numbers, "
                "dates, and versions. Do not invent entities, facts, or answer terms. "
                "Return only strict JSON with exactly one field: "
                '{"queries": ["..."]}.'
            )
        else:
            system_prompt = (
                "Create retrieval queries with distinct responsibilities, "
                "in this order: (1) expand abbreviations, terminology aliases, "
                "and full names already supported by the query; (2) produce a "
                "concise keyword-focused search query, removing empty pronouns "
                "without guessing missing entities. Preserve the original intent "
                "and never invent answer terms or facts. Return at most "
                f"{limit} queries and only strict JSON with exactly one field: "
                '{"queries": ["..."]}.'
            )

        payload = {
            "model": self.config.model,
            "temperature": 0,
            "max_tokens": 256,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {"role": "user", "content": query},
            ],
        }
        if self.config.api_base.rstrip("/") == "https://api.deepseek.com":
            payload["thinking"] = {"type": "disabled"}

        try:
            response = self._post(payload)
            content = response["choices"][0]["message"]["content"]
            variants = self._parse_variants(content, query, limit)
            if cross_language and any(contains_cjk(variant) for variant in variants):
                raise ValueError("cross-language rewrite must return English queries")
            return variants, "success" if variants else "empty"
        except TimeoutError:
            self.logger.warning("[QUERY_REWRITE_TIMEOUT]")
            return [], "timeout"
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.logger.warning("[QUERY_REWRITE_INVALID] error=%s", exc)
            return [], "invalid"
        except Exception as exc:
            if self._is_timeout(exc):
                self.logger.warning("[QUERY_REWRITE_TIMEOUT] error=%s", exc)
                return [], "timeout"
            self.logger.warning("[QUERY_REWRITE_ERROR] error=%s", exc)
            return [], "error"

    def _post(self, payload: dict) -> dict:
        url = f"{self.config.api_base.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        if self.request_client is not None:
            response = self.request_client.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.config.timeout_ms / 1000.0,
            )
        else:
            import httpx

            response = httpx.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.config.timeout_ms / 1000.0,
            )
        response.raise_for_status()
        return response.json()

    def _parse_variants(self, content: str, original: str, limit: int) -> List[str]:
        data = json.loads(content)
        if not isinstance(data, dict) or set(data) != {"queries"}:
            raise ValueError("rewrite response must contain only the queries field")
        queries = data["queries"]
        if not isinstance(queries, list):
            raise ValueError("queries must be a list")

        original_key = original.strip().casefold()
        seen = {original_key}
        variants = []
        for value in queries:
            if not isinstance(value, str):
                raise ValueError("every query variant must be a string")
            candidate = value.strip()
            if not candidate or len(candidate) > self.config.max_query_chars:
                continue
            key = candidate.casefold()
            if key in seen:
                continue
            seen.add(key)
            variants.append(candidate)
            if len(variants) >= limit:
                break
        return variants

    @staticmethod
    def _is_timeout(exc: Exception) -> bool:
        return "timeout" in type(exc).__name__.lower()
