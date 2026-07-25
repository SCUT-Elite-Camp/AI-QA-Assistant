# CP2 ToolRegistry 适配接口

## 所有权

Toolset 是 `ToolRegistry` 的唯一所有者。

Agent 不保存第二份工具字典，不负责：

- 注册和注销工具。
- 重复工具名处理。
- 动态加载工具。
- 工具启用和停用。

这些行为全部由 Toolset Registry 决定。

## Agent 适配器

Agent 通过只读的 `ToolRegistryAdapter` 消费 Toolset Registry：

```python
from agent.tools import ToolRegistryAdapter
from toolset.tool_layer.registry import ToolRegistry as ToolsetRegistry

toolset_registry = ToolsetRegistry()
registry = ToolRegistryAdapter(toolset_registry)
```

适配器不包含 `_tools`，只保存 Toolset Registry 引用。

## 标准读取接口

```python
registry.get(name)
registry.list_tools()
registry.to_openai_schemas()
registry.list_tool_metadata()
```

含义：

- `get(name)`：委托 `ToolsetRegistry.get_tool(name)`。
- `list_tools()`：委托 `ToolsetRegistry.get_all_tools()`。
- `to_openai_schemas()`：委托 `ToolsetRegistry.get_tool_schemas()`。
- `list_tool_metadata()`：根据 Toolset 当前工具视图生成公开元数据。

Toolset Registry 发生变化后，Adapter 下一次读取立即得到最新结果，不需要同步第二份状态。

## CP1 临时兼容接口

现有 Agent 暂时仍可使用：

```python
registry.get_tool(name)
registry.get_all_tools()
registry.get_tool_schemas()
```

这些方法只是读取别名。Adapter 不提供 `register`、`unregister` 或 `load_tools`。

## GET /api/tools

`GET /api/tools` 通过 Adapter 读取 Toolset Registry，并返回：

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

`enabled` 目前来自 Toolset 工具属性；未提供该属性时默认展示为 `true`。
是否真正加载或允许调用该工具，最终由 Toolset 和后续 IntentPolicy 共同控制。
