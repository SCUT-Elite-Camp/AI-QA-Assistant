from tool_layer.registry import ToolRegistry


def test_library_tool_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("PERSONAL_LIBRARY_ENABLED", raising=False)
    assert ToolRegistry().get_tool("search_library") is None


def test_library_tool_requires_explicit_enable(monkeypatch):
    monkeypatch.setenv("PERSONAL_LIBRARY_ENABLED", "true")
    assert ToolRegistry().get_tool("search_library") is not None
