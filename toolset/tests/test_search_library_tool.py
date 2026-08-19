import hashlib
import hmac
import json

from tool_layer.search_library_tool import SearchLibraryTool


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self):
        return b'{"items": []}'


def test_schema_does_not_expose_authorization_fields():
    properties = SearchLibraryTool().parameters["properties"]
    assert "owner_user_id" not in properties
    assert "knowledge_base_id" not in properties
    assert "source_scope" not in properties


def test_signed_context_is_injected_and_doc_ids_remain_scoped(monkeypatch):
    secret = "test-secret"
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", secret)
    captured = {}

    def fake_open(request, timeout):
        captured.update(json.loads(request.data.decode("utf-8")))
        return _Response()

    monkeypatch.setattr("tool_layer.search_library_tool.urlopen", fake_open)
    token = hmac.new(secret.encode(), b"user-a:kb-a", hashlib.sha256).hexdigest()
    tool = SearchLibraryTool()
    tool.set_request_context("user-a", "kb-a", token)
    tool.execute(query="risk", mode="bm25", doc_ids=["doc-from-model"])

    assert captured["owner_id"] == "user-a"
    assert captured["knowledge_base_id"] == "kb-a"
    assert captured["doc_ids"] == ["doc-from-model"]


def test_invalid_context_fails_closed(monkeypatch):
    monkeypatch.setenv("ATTACHMENT_INTERNAL_SECRET", "test-secret")
    tool = SearchLibraryTool()
    tool.set_request_context("user-a", "kb-a", "0" * 64)
    assert tool.execute(query="secret") == {"error": "library_context_unavailable", "items": []}
