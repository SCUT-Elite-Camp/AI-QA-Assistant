# CP2 ToolRegistry Adapter Contract

## Ownership

Toolset is the single owner of `ToolRegistry`.

The Agent layer must not maintain a second tool dictionary and is not
responsible for:

- registering or unregistering tools;
- resolving duplicate tool names;
- dynamically loading tools;
- enabling or disabling tools.

These behaviors are owned by Toolset.

## Agent Adapter

The Agent consumes the Toolset registry through the read-only
`ToolRegistryAdapter`:

```python
from agent.tools import ToolRegistryAdapter
from toolset.tool_layer.registry import ToolRegistry as ToolsetRegistry

toolset_registry = ToolsetRegistry()
registry = ToolRegistryAdapter(toolset_registry)
```

The adapter does not contain `_tools`. It stores only a reference to the
Toolset registry.

## Read Interfaces

```python
registry.get(name)
registry.list_tools()
registry.to_openai_schemas()
registry.list_tool_metadata()
```

- `get(name)` delegates to `ToolsetRegistry.get_tool(name)`.
- `list_tools()` delegates to `ToolsetRegistry.get_all_tools()`.
- `to_openai_schemas()` delegates to
  `ToolsetRegistry.get_tool_schemas()`.
- `list_tool_metadata()` builds public metadata from the current Toolset
  registry view.

When the Toolset registry changes, the next adapter read immediately reflects
that change. No state synchronization is required.

## Temporary CP1 Compatibility

The current CP1 Agent may still use these read aliases:

```python
registry.get_tool(name)
registry.get_all_tools()
registry.get_tool_schemas()
```

The adapter intentionally does not expose `register`, `unregister`, or
`load_tools`.

## GET /api/tools

`GET /api/tools` reads the Toolset registry through the adapter and returns:

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

The `enabled` value is read from the Toolset tool when available and defaults
to `true`. Whether a tool may actually be called is ultimately controlled by
Toolset and the future `IntentPolicy`.
