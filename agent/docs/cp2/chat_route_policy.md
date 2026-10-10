# CP2 ChatRoutePolicy v1

## 目的

`ChatRoutePolicy` 是普通 `POST /api/chat` 的内部路由策略。它只负责把已经通过 Query Understanding 的 `QueryPlan` 映射到 Chat 的 L0/L1/L2 三个有界路径。

它不创建 Research Job，也不接受模型输出的 `route`、`mode` 或预算字段。CP2 的 Research 入口必须由用户显式触发，后续会通过独立 API 接入。

## 路由表

| 路由 | 条件 | 行为 |
|---|---|---|
| `chat_l0_direct` | `casual_chat`、`system_help`、`unsupported` | 不进入检索；由现有 IntentPolicy 决定直接回答或拒绝 |
| `chat_l1_retrieval` | 普通知识问答、文档搜索、总结 | 进入当前受限 Chat 检索链路 |
| `chat_l2_bounded_multi_step` | `comparison` 或存在有限 `sub_queries` | 进入当前有界多步 Chat 链路，仍受既有工具、迭代和预算限制 |

当前 `ChatRoute` 枚举没有 Research 路由。`ChatRouteDecision.research_entry_allowed` 固定为 `false`，仅用于内部断言和测试，不作为 Web 响应字段。

## 安全边界

- `/api/chat` 的调用图不依赖 `ResearchJobService`。
- Query Understanding 只能返回现有 Chat `QueryIntent`，不接受 `research` 意图。
- 模型返回 `research`、`deep research` 或 `mode=research` 时，结构化解析失败并回退到安全的 `knowledge_qa`，不会改变执行路径。
- 模型在 Tool Call 中传入的 `mode` 和 `top_k` 会被 Runner 的请求约束覆盖。
- Chat 的五字段 `ChatResponse` 保持不变。

## 测试

- `tests/unit/test_chat_route_policy.py`
  - 验证 L0/L1/L2 映射；
  - 验证枚举不存在 Research 路由；
  - 验证模型伪造 `research` 意图时安全回退。
- `tests/integration/test_chat_research_boundary.py`
  - 验证模型 Tool Call 不能把检索模式改成 `research`；
  - 验证仍然使用请求约束的 `hybrid` 和 `top_k`。

