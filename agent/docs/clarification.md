# CP2 Clarifier 接口说明

## 目标

`Clarifier` 在查询重写和检索之前判断用户问题是否缺少必要信息。
只有无法从会话历史安全确定真实意图时才要求用户澄清。

## 接口

```python
from agent.query import Clarifier, ClarificationDecision

decision = Clarifier().evaluate(
    query="它有什么问题？",
    history=[],
)
```

返回示例：

```python
ClarificationDecision(
    needs_clarification=True,
    question="请问你指的是 Agent 层、Web 层，还是整个项目？",
    reason="问题缺少明确的业务对象",
)
```

## 应当澄清

- “它”“这个”“那个”无法从历史确定指代。
- 问题只有“怎么做”“有什么问题”等表述，没有主题。
- 一个问题可能对应多个明显不同的业务对象。
- 检索必须依赖缺失的时间、模块、文档或范围条件。

## 不应澄清

- 问题虽短但含义明确，例如“什么是 RAG？”。
- 会话历史已经能够确定指代。
- 查询重写即可把问题变成独立检索查询。
- 只是措辞不规范，但真实意图明确。

## 配置

```env
CLARIFICATION_ENABLED=true
```

设置为 `false` 时不调用模型，直接继续后续流程。

## 失败降级

模型异常、非法 JSON、缺少字段，或模型判断需要澄清却没有返回问题时：

```python
ClarificationDecision(
    needs_clarification=False,
    question="",
    reason="clarification_check_failed",
)
```

辅助判断失败时默认继续流程，避免阻塞所有问答。

## 推荐接入顺序

```text
请求参数校验
    ↓
按 session_id 读取会话历史
    ↓
Clarifier.evaluate(query, history)
    ├─ 需要澄清
    │    ↓
    │  返回 clarification_required
    │    ↓
    │  将澄清问题写入 ConversationMemory
    │
    └─ 不需要澄清
         ↓
       QueryRewriter.rewrite(query, history)
         ↓
       SearchTool
```

触发澄清时不得调用查询重写或 SearchTool。

当前提交提供 Clarifier、`ClarificationDecision` 和
`StatusCode.CLARIFICATION_REQUIRED`，暂不修改 `Agent.chat()`。

