# CP2 ToolRegistry 接口说明

## 目标

Agent 层通过 `agent.tools.ToolRegistry` 管理可供 Agent 调用的工具。
工具实现仍由 Toolset 层提供，Agent 层只负责注册、查询、公开 Schema 和加载隔离。

## 标准接口

```python
registry.register(tool)
registry.register(tool, overwrite=True)
registry.unregister(name)
registry.get(name)
registry.list_tools()
registry.load_tools()
registry.to_openai_schemas()
```

## 行为约定

- `register(tool)` 默认拒绝重复名称并抛出 `DuplicateToolError`。
- 只有显式传入 `overwrite=True` 时才替换已注册工具。
- `TOOL_AUTOLOAD_ENABLED=true` 时默认从 Toolset 的 `get_tools()` 加载工具。
- `load_tools(loaders)` 中单个加载器或工具失败，不阻断后续加载。
- 加载失败会记录日志，并由 `load_tools()` 返回错误信息列表。

## 兼容接口

现有 Agent 可继续使用以下旧方法：

```python
registry.register_tool(tool)
registry.unregister_tool(name)
registry.get_tool(name)
registry.get_all_tools()
registry.get_tool_schemas()
```

这些方法是兼容别名。CP2 新代码应优先使用标准接口。

## GET /api/tools

接口返回工具元数据：

```json
[
  {
    "name": "search_documents",
    "description": "Search the document database...",
    "parameters": {
      "type": "object",
      "properties": {},
      "required": ["query"]
    },
    "enabled": true
  }
]
```

`to_openai_schemas()` 单独生成传给 LLM 的 OpenAI function calling 结构。
