# CP2 Agent 双人协作接口契约

> 状态：草案，尚未冻结。若本文与 `query_plan_contract.md`、
> `tool_registry.md` 等最新专项契约冲突，以专项契约和最新版 CP2
> 优化计划为准。待其余公共 Schema 分阶段确认后再统一修订本文。

## 1. 文档目的

本文用于约定 xdj 与 lhf 在 CP2 阶段并行开发时共同依赖的接口。

- xdj 负责：ConversationMemory 接入、Agent 多轮循环、停止条件和主流程编排。
- lhf 负责：ToolRegistry、QueryRewriter、Clarifier 及相关测试。
- 共同负责：共享 Schema、`Agent.chat()` 集成、Web 响应契约和集成测试。

双方实现可以独立调整内部代码，但不得在未同步的情况下修改本文约定的公共方法签名、消息结构和调用顺序。

---

## 2. 总体调用顺序

```text
收到 ChatRequest
    ↓
校验 query
    ↓
创建并绑定 trace_id
    ↓
读取 ConversationMemory
    ↓
Clarifier.evaluate(query, history)
    ├─ needs_clarification = true
    │    ↓
    │  保存当前用户问题
    │    ↓
    │  保存 Agent 澄清问题
    │    ↓
    │  返回 clarification_required
    │
    └─ needs_clarification = false
         ↓
       QueryRewriter.rewrite(query, history)
         ↓
       使用 rewritten_query 进入 Agent Loop
         ↓
       ToolRegistry 向 LLM 提供工具 Schema
         ↓
       LLM 返回 tool_calls
         ↓
       ToolRegistry 按名称查找并执行工具
         ↓
       工具结果加入 messages
         ↓
       LLM 不再请求工具时结束
         ↓
       保存原始用户问题和最终 Agent 回答
         ↓
       返回 ChatResponse
```

必须遵守：

1. Clarifier 在 QueryRewriter 之前执行。
2. 触发澄清时不得调用 QueryRewriter、SearchTool 或其他业务工具。
3. `rewritten_query` 只用于检索和工具调用。
4. 最终回答仍针对 `original_query`。
5. 同一次请求的所有步骤共用同一个 `trace_id`。

---

## 3. ChatRequest 约定

沿用现有结构：

```python
class ChatRequest(BaseModel):
    query: str
    session_id: str | None = None
    top_k: int = 5
    filters: dict | None = None
    stream: bool = False
    retrieval_mode: Literal["vector", "bm25", "hybrid"] = "hybrid"
```

### session_id 规则

- `session_id` 有值：读取和写入对应会话。
- `session_id` 为空：本次请求按无历史的单轮问答执行。
- 不得使用固定默认 session 保存所有匿名请求，避免不同用户串话。
- 不同 `session_id` 的消息必须完全隔离。

---

## 4. ConversationMemory 接口

由 xdj 提供，lhf 的 Clarifier 和 QueryRewriter 只依赖以下接口：

```python
class ConversationMemory:
    def get_messages(self, session_id: str) -> list[dict]:
        ...

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
    ) -> None:
        ...

    def clear(self, session_id: str) -> None:
        ...
```

### 消息格式

`get_messages()` 返回：

```python
[
    {
        "role": "user",
        "content": "介绍 Agent 层的 Q1 成果",
    },
    {
        "role": "assistant",
        "content": "Agent 层已经完成单轮 RAG 流程。",
    },
]
```

基础会话记忆只要求保存：

- `role="user"`
- `role="assistant"`

Agent Loop 内部产生的 `tool` 消息属于单次执行上下文，第一版不要求长期写入 ConversationMemory。

### Memory 行为

- 消息按写入时间从旧到新返回。
- 返回值必须是新列表，调用方修改后不能污染内部存储。
- 超过 `MAX_MEMORY_MESSAGES` 时保留最新消息。
- `clear(session_id)` 只清空指定会话。
- 未知 `session_id` 的 `get_messages()` 返回空列表。
- Memory 内部应保证并发访问安全。

### 写入时机

普通回答：

```text
保存原始用户问题
→ 保存最终 Agent 回答
```

澄清回答：

```text
保存原始用户问题
→ 保存 Agent 澄清问题
```

不得把 `rewritten_query` 当作用户消息写入 Memory。

---

## 5. Clarifier 接口

由 lhf 提供：

```python
from agent.query import Clarifier, ClarificationDecision

decision = clarifier.evaluate(
    query: str,
    history: list[dict],
) -> ClarificationDecision
```

返回结构：

```python
class ClarificationDecision(BaseModel):
    needs_clarification: bool
    question: str = ""
    reason: str = ""
```

### 结果处理

```python
if decision.needs_clarification:
    # 不执行 QueryRewriter 和工具
    # 将 decision.question 放入 ChatResponse.message
```

约束：

- `needs_clarification=True` 时 `question` 必须非空。
- `needs_clarification=False` 时调用方忽略 `question`。
- Clarifier 自身异常时默认返回不澄清，由后续流程继续处理。
- `reason` 只用于日志和调试，不直接展示给用户。

---

## 6. QueryRewriter 接口

由 lhf 提供：

```python
from agent.query import QueryRewriter, RewriteResult

result = rewriter.rewrite(
    query: str,
    history: list[dict],
) -> RewriteResult
```

返回结构：

```python
class RewriteResult(BaseModel):
    original_query: str
    rewritten_query: str
    changed: bool
    reason: str = ""
```

### 使用规则

```python
search_query = result.rewritten_query
```

- `original_query` 用于生成最终回答、审计日志和 Memory 写入。
- `rewritten_query` 用于 SearchTool 或其他检索工具。
- `reason` 只用于日志和调试。
- 重写失败时模块自动将 `rewritten_query` 回退为原问题。
- 主流程不得因为 `changed=False` 而跳过正常检索。

---

## 7. ToolRegistry 接口

由 lhf 提供：

```python
registry.get(name)
registry.list_tools()
registry.to_openai_schemas()
registry.register(tool)
registry.unregister(name)
```

现有兼容接口：

```python
registry.get_tool(name)
registry.get_all_tools()
registry.get_tool_schemas()
```

CP2 新代码优先使用标准接口。

### Agent Loop 使用方式

向 LLM 提供工具：

```python
response = llm.chat(
    messages=messages,
    tools=registry.to_openai_schemas(),
)
```

查找工具：

```python
tool = registry.get(tool_name)
if tool is None:
    # 按工具不存在处理
```

执行工具：

```python
result = tool.execute(**arguments)
```

---

## 8. Tool Call 消息约定

LLM 返回的工具请求示例：

```python
{
    "role": "assistant",
    "content": None,
    "tool_calls": [
        {
            "id": "call-001",
            "type": "function",
            "function": {
                "name": "search_documents",
                "arguments": "{\"query\":\"Agent 层 Q1 分工\"}",
            },
        },
    ],
}
```

Agent 必须先把该 assistant 消息加入 `messages`，再执行工具。

工具结果消息：

```python
{
    "role": "tool",
    "tool_call_id": "call-001",
    "name": "search_documents",
    "content": "工具结果的字符串或 JSON 字符串",
}
```

约束：

- `arguments` 必须通过 `json.loads()` 解析。
- 解析结果必须是 JSON object，即 Python `dict`。
- 不允许直接执行模型返回的代码或表达式。
- 工具结果必须安全转换成字符串或 JSON 字符串。
- 一个 assistant 消息包含多个 `tool_calls` 时，按返回顺序执行。

---

## 9. Agent Loop 停止条件

主流程在以下情况停止：

1. LLM 返回普通回答且没有 `tool_calls`。
2. Clarifier 返回需要澄清。
3. 达到 `MAX_AGENT_ITERATIONS`。
4. LLM 或工具发生不可恢复异常。
5. 连续重复调用相同工具和相同参数达到限制。

重复调用 key：

```python
tool_call_key = (
    tool_name,
    normalized_arguments,
)
```

其中 `normalized_arguments` 建议使用：

```python
json.dumps(arguments, sort_keys=True, ensure_ascii=False)
```

---

## 10. 配置项

双方统一使用：

```env
MEMORY_ENABLED=true
MAX_MEMORY_MESSAGES=10
MAX_AGENT_ITERATIONS=5
MAX_REPEATED_TOOL_CALLS=2

TOOL_AUTOLOAD_ENABLED=true
QUERY_REWRITE_ENABLED=true
CLARIFICATION_ENABLED=true
```

配置关闭时的行为：

- `MEMORY_ENABLED=false`：history 使用空列表，不读取或写入 Memory。
- `QUERY_REWRITE_ENABLED=false`：使用原始问题。
- `CLARIFICATION_ENABLED=false`：不进行澄清判断。
- `TOOL_AUTOLOAD_ENABLED=false`：不自动加载默认工具，由调用方手动注入。

---

## 11. ChatResponse 与状态码

现有结构保持不变：

```python
class ChatResponse(BaseModel):
    trace_id: str
    status: str
    answer: str
    message: str
    citations: list[Citation]
```

澄清响应：

```json
{
  "trace_id": "trace-xxxx",
  "status": "clarification_required",
  "answer": "",
  "message": "请问你指的是 Agent 层、Web 层，还是整个项目？",
  "citations": []
}
```

状态码：

```text
success
invalid_query
clarification_required
no_relevant_context
retrieval_error
llm_error
```

澄清响应不得携带 citations。

---

## 12. 异常归属和降级

| 场景 | 处理 |
|---|---|
| Memory 读取失败 | 记录日志，使用空历史继续 |
| Memory 写入失败 | 记录日志，不覆盖已经生成的正常回答 |
| Clarifier 失败 | 不澄清，继续 QueryRewriter |
| QueryRewriter 失败 | 使用原始问题 |
| 工具不存在 | 返回明确工具错误并停止当前循环 |
| 工具参数不是合法 JSON | 返回明确参数错误并停止当前循环 |
| 工具执行异常 | 映射为工具/检索异常 |
| LLM 调用异常 | 返回 `llm_error` |
| 达到最大迭代次数 | 安全停止，不继续调用 LLM 或工具 |

辅助模块降级不得改变当前请求的 `trace_id`。

---

## 13. 依赖注入约定

为了便于双方测试，Agent 构造函数应允许注入：

```python
Agent(
    llm=fake_llm,
    tools=[fake_tool],
    memory=fake_memory,
    clarifier=fake_clarifier,
    query_rewriter=fake_rewriter,
)
```

生产环境参数为空时使用默认实现。

这样 Agent 主流程测试不需要真实：

- Milvus
- embedding 模型
- Ollama
- 外部网络

---

## 14. 双方集成测试清单

### Memory

- 同一 session 能读取上一轮消息。
- 不同 session 完全隔离。
- 无 session_id 时正常单轮问答。
- 消息达到上限后只保留最新内容。
- `clear()` 只影响指定 session。

### 澄清

- 无法确定指代时返回 `clarification_required`。
- 明确问题不触发澄清。
- 历史可以确定指代时不触发澄清。
- 澄清时不调用 QueryRewriter 和工具。
- 澄清问题写入 Memory。
- 用户补充后能够继续原任务。

### 查询重写

- SearchTool 收到 `rewritten_query`。
- 最终回答仍对应 `original_query`。
- 重写失败时使用原始问题。
- 模块名和专业术语保持不变。

### Agent Loop

- 一轮工具调用后继续请求 LLM。
- 支持连续调用不同工具。
- 没有 `tool_calls` 时主动停止。
- 达到最大迭代次数时停止。
- 重复工具调用达到限制时停止。
- 非法工具名和非法 JSON 参数有明确错误。
- 多轮执行过程中 `trace_id` 保持一致。

---

## 15. 合并前确认事项

双方合并代码前共同确认：

- [ ] Memory 方法签名与本文一致。
- [ ] history 消息格式为 `role + content`。
- [ ] Clarifier 在 QueryRewriter 之前执行。
- [ ] 澄清时没有调用工具。
- [ ] SearchTool 收到重写后的问题。
- [ ] Memory 保存的是原始问题，不是重写问题。
- [ ] 工具消息符合 OpenAI tool message 格式。
- [ ] 所有步骤使用同一 `trace_id`。
- [ ] Mock 集成测试不依赖 Milvus 和 Ollama。
- [ ] Web 能识别 `clarification_required`。
