# CP2 QueryRewriter 接口说明

## 目标

`QueryRewriter` 结合当前用户问题和会话历史，生成可以独立理解、适合知识库检索的查询。
重写只服务于检索，最终回答仍必须针对用户的原始问题。

## 接口

```python
from agent.query import QueryRewriter, RewriteResult

result = QueryRewriter().rewrite(
    query="那它有哪些不足？",
    history=[
        {"role": "user", "content": "介绍 Agent 层的 Q1 成果"},
        {"role": "assistant", "content": "Agent 层完成了单轮 RAG 流程。"},
    ],
)
```

返回：

```python
RewriteResult(
    original_query="那它有哪些不足？",
    rewritten_query="Agent 层 Q1 阶段当前实现有哪些不足？",
    changed=True,
    reason="结合历史补全指代对象",
)
```

## 行为约定

- 不改变用户原始意图。
- 不添加对话历史中不存在的事实。
- 保留模块名、接口名、代码标识符和专业术语。
- 明确的问题可以保持原文。
- `original_query` 由程序保存，不采用模型返回的原问题。
- 历史仅接受 `user` 和 `assistant` 的字符串消息。
- 模型异常、非法 JSON、空结果或结构校验失败时，回退到原始问题。

## 配置

```env
QUERY_REWRITE_ENABLED=true
```

设置为 `false` 时不调用模型，直接返回原始问题。

## 推荐接入顺序

```text
按 session_id 读取会话历史
    ↓
判断是否需要澄清
    ↓
QueryRewriter.rewrite(query, history)
    ↓
将 rewritten_query 传给 SearchTool
    ↓
使用 original_query 生成最终回答
```

当前提交只提供可独立测试的 QueryRewriter，不在 `Agent.chat()` 中提前接入。
待 ConversationMemory 和澄清接口就绪后，再按上述顺序完成集成。

