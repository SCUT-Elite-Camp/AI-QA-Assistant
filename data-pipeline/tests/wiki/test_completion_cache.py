from __future__ import annotations

from pipeline.wiki.cache import CachingJsonCompletionClient


class FakeClient:
    model = "fake-model"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, **_kwargs):
        self.calls += 1
        return {"value": self.calls}


class FakeCache:
    def __init__(self) -> None:
        self.values = {}

    def get_completion(self, cache_key):
        return self.values.get(cache_key)

    def put_completion(self, cache_key, **kwargs):
        self.values[cache_key] = kwargs["response"]


def test_cache_reuses_only_the_exact_completion_request() -> None:
    backend, cache = FakeClient(), FakeCache()
    client = CachingJsonCompletionClient(backend, cache)
    request = {
        "system": "extract", "user": {"text": "RAG"}, "schema_name": "unit",
        "schema": {"type": "object"}, "max_tokens": 100,
    }

    assert client.complete(**request) == {"value": 1}
    assert client.complete(**request) == {"value": 1}
    assert client.complete(**{**request, "max_tokens": 101}) == {"value": 2}
    assert backend.calls == 2
    assert client.cache_hits == 1 and client.cache_misses == 2
