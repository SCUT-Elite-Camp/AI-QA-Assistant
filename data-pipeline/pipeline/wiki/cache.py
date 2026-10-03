"""Deterministic completion caching for resumable offline Wiki builds."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from .extraction import JsonCompletionClient


class CompletionCache(Protocol):
    def get_completion(self, cache_key: str) -> dict[str, Any] | None: ...
    def put_completion(
        self, cache_key: str, *, model: str, schema_name: str, response: dict[str, Any],
    ) -> None: ...


class CachingJsonCompletionClient:
    """Cache only complete, parsed JSON responses using the entire model request."""

    def __init__(self, client: JsonCompletionClient, cache: CompletionCache) -> None:
        self.client = client
        self.cache = cache
        self.model = client.model
        self.cache_hits = 0
        self.cache_misses = 0

    def complete(
        self, *, system: str, user: dict[str, Any], schema_name: str,
        schema: dict[str, Any], max_tokens: int = 2400,
    ) -> dict[str, Any]:
        request = {
            "model": self.model,
            "system": system,
            "user": user,
            "schema_name": schema_name,
            "schema": schema,
            "max_tokens": max_tokens,
        }
        cache_key = hashlib.sha256(json.dumps(
            request, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        cached = self.cache.get_completion(cache_key)
        if cached is not None:
            self.cache_hits += 1
            return cached
        self.cache_misses += 1
        response = self.client.complete(
            system=system, user=user, schema_name=schema_name, schema=schema,
            max_tokens=max_tokens,
        )
        if not isinstance(response, dict):
            raise ValueError("Wiki completion cache accepts JSON objects only")
        self.cache.put_completion(
            cache_key, model=self.model, schema_name=schema_name, response=response,
        )
        return response
