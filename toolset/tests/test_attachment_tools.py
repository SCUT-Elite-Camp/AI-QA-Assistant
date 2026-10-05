from tool_layer.attachment_tools import InspectAttachmentTool, SearchAttachmentsTool
from tool_layer.registry import ToolRegistry


def test_attachment_tools_are_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ATTACHMENTS_ENABLED", raising=False)
    registry = ToolRegistry()
    assert registry.get_tool("search_attachments") is None
    assert registry.get_tool("inspect_attachment") is None


def test_attachment_tools_require_explicit_enable(monkeypatch):
    monkeypatch.setenv("ATTACHMENTS_ENABLED", "true")
    registry = ToolRegistry()
    assert registry.get_tool("search_attachments") is not None
    assert registry.get_tool("inspect_attachment") is not None


def test_search_prefers_selected_ids_without_leaving_allowlist(monkeypatch):
    tool = SearchAttachmentsTool()
    tool.set_request_context(["att_selected", "att_other"], ["att_selected"])
    calls = []

    def fake_request(path, payload, **_kwargs):
        calls.append((path, payload))
        attachment_id = payload["attachment_ids"][0]
        return {"items": [{
            "attachment_id": attachment_id,
            "evidence_id": f"aev_{len(calls)}",
            "content": attachment_id,
        }]}

    monkeypatch.setattr(tool, "_request", fake_request)
    result = tool.execute(query="risk", top_k=4)

    assert calls[0][1]["attachment_ids"] == ["att_selected", "att_other"]
    assert calls[1][1]["attachment_ids"] == ["att_selected"]
    assert result["items"][0]["attachment_id"] == "att_selected"


def test_inspection_rejects_non_allowlisted_attachment(monkeypatch):
    tool = InspectAttachmentTool()
    tool.set_request_context(["att_allowed"], [])
    monkeypatch.setattr(tool, "_request", lambda *_args, **_kwargs: {"content": "leak"})

    assert tool.execute(attachment_id="att_other", question="read") == {
        "error": "attachment_forbidden",
        "items": [],
    }
