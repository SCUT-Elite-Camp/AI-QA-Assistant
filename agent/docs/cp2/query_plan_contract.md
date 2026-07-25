# CP2 QueryIntent 与 QueryPlan 接口契约

## 1. 适用范围

本文只冻结以下公共 Schema：

- `QueryIntent`
- `QueryPlan`

本阶段不包含 IntentClassifier、Query Understanding、PolicyRouter 或 Agent Runner 的具体实现。

## 2. 数据流

```text
用户问题 + 会话历史
        ↓
Query Understanding（后续实现）
        ↓
QueryPlan
        ↓
IntentPolicy / Agent Runner（后续实现）
```

生产方：

- Query Understanding

消费方：

- PolicyRouter
- Agent Runner
- 运行日志和 RunSummary

## 3. QueryIntent

```python
class QueryIntent(StrEnum):
    KNOWLEDGE_QA = "knowledge_qa"
    DOCUMENT_SEARCH = "document_search"
    SUMMARIZATION = "summarization"
    COMPARISON = "comparison"
    CASUAL_CHAT = "casual_chat"
    SYSTEM_HELP = "system_help"
    UNSUPPORTED = "unsupported"
```

`QueryIntent` 是意图识别结果，不负责执行意图识别。

| 意图 | 含义 |
|---|---|
| `knowledge_qa` | 基于知识证据回答问题 |
| `document_search` | 查找文档或文档列表 |
| `summarization` | 总结一份或多份资料 |
| `comparison` | 比较两个或多个对象 |
| `casual_chat` | 不需要检索的普通交流 |
| `system_help` | 询问系统能力和使用方法 |
| `unsupported` | 当前系统不支持的请求 |

不得由 LLM 自由生成枚举之外的意图名称。

## 4. QueryPlan

```python
class QueryPlan(BaseModel):
    original_query: str
    standalone_query: str

    intent: QueryIntent = QueryIntent.KNOWLEDGE_QA
    intent_confidence: float = 1.0

    is_follow_up: bool = False
    is_clarification_reply: bool = False

    needs_clarification: bool = False
    clarification_question: str = ""
    ambiguity_reason: str = ""

    sub_queries: list[str] = []
    filters: dict[str, Any] = {}
```

实际代码使用 `default_factory` 创建 `sub_queries` 和 `filters`，不同请求之间不会共享可变对象。

## 5. 字段语义

### original_query

用户本轮提交的原始问题。

- 用于最终回答。
- 用于 ConversationMemory。
- 用于审计记录。
- 不得替换成重写后的问题。

### standalone_query

结合历史完成指代消解后的独立查询。

- 用于检索和工具调用。
- 自动清理首尾空白。
- 重写失败时等于原始问题。

### intent

意图识别结果。无法可靠识别或 Query Understanding 失败时，安全回退为：

```python
QueryIntent.KNOWLEDGE_QA
```

### intent_confidence

意图识别置信度，取值范围：

```text
0.0 <= intent_confidence <= 1.0
```

置信度只用于策略和日志，不能让模型凭借高置信度突破 Policy 硬限制。

### is_follow_up

当前问题是否依赖前文。

例如：

```text
上一轮：介绍 Agent 层。
当前：它有什么不足？
```

### is_clarification_reply

当前消息是否是在回答系统上一轮提出的澄清问题。

例如：

```text
Agent：请问需要比较哪些对象？
用户：Q1 和 CP2。
```

### needs_clarification

是否必须先询问用户才能继续。

为 `true` 时：

- `clarification_question` 必须非空。
- 不得调用检索工具。
- 不得进入普通 Agent Runner。

### clarification_question

向用户展示的一个具体澄清问题。

当 `needs_clarification=false` 时，该字段会被规范化为空字符串。

### ambiguity_reason

歧义原因，只用于日志和调试，不直接展示给用户。

### sub_queries

复杂查询拆分结果。

例如比较任务：

```python
[
    "Agent CP1 的目标和实现",
    "Agent CP2 的目标和实现",
]
```

空字符串子查询会被清理。

### filters

从用户请求和上下文中提取的结构化检索过滤条件。

强制过滤条件不得在纠正检索时被模型自行删除。

## 6. 示例

### 普通知识问答

```python
QueryPlan(
    original_query="CP2 的目标是什么？",
    standalone_query="Agent 层 CP2 的目标是什么？",
    intent=QueryIntent.KNOWLEDGE_QA,
    intent_confidence=0.96,
)
```

### 会话追问

```python
QueryPlan(
    original_query="它有哪些不足？",
    standalone_query="Agent 层 CP1 当前实现有哪些不足？",
    intent=QueryIntent.KNOWLEDGE_QA,
    intent_confidence=0.94,
    is_follow_up=True,
)
```

### 模糊比较

```python
QueryPlan(
    original_query="帮我比较一下",
    standalone_query="帮我比较一下",
    intent=QueryIntent.COMPARISON,
    intent_confidence=0.91,
    needs_clarification=True,
    clarification_question="请问需要比较哪些对象？",
    ambiguity_reason="缺少比较对象",
)
```

### 明确比较

```python
QueryPlan(
    original_query="比较 CP1 和 CP2",
    standalone_query="比较 Agent 层 CP1 和 CP2",
    intent=QueryIntent.COMPARISON,
    intent_confidence=0.98,
    sub_queries=[
        "Agent 层 CP1 的目标和实现",
        "Agent 层 CP2 的目标和实现",
    ],
)
```

## 7. 校验规则

- `original_query` 不能为空或纯空白。
- `standalone_query` 不能为空或纯空白。
- `intent_confidence` 必须在0到1之间。
- `needs_clarification=true` 时必须有具体澄清问题。
- `needs_clarification=false` 时清空无用的澄清问题。
- 未知字段被拒绝，避免双方接口静默漂移。
- JSON 序列化时 `intent` 输出为字符串，例如 `"comparison"`。

## 8. 双方确认事项

- [ ] Query Understanding 只返回本文定义的意图。
- [ ] Agent Runner 使用 `standalone_query` 检索。
- [ ] 最终回答和 Memory 使用 `original_query`。
- [ ] `needs_clarification=true` 时不调用工具。
- [ ] PolicyRouter 不修改 QueryPlan 中记录的用户事实。
- [ ] 新增或修改字段前先更新本文并通知双方。
