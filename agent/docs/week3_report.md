# Week 3 工作报告

## 完成时间

2026-06-26

## 本周目标

Week 3 的目标是让 Agent 在单轮 RAG 链路已经跑通的基础上，更稳定、更可信地处理异常、低相关上下文和引用一致性问题。

## 已完成内容

### 1. no_relevant_context 兜底

- 检索结果为空时，Agent 直接返回 `no_relevant_context`。
- 检索结果低于 `MIN_RETRIEVAL_SCORE` 时，Agent 过滤低相关内容。
- 过滤后无可用上下文时，不调用 LLM，直接返回信息不足提示。

### 2. retrieval_error 处理

- 检索工具异常会被统一捕获。
- Tool Layer 不可导入、后端异常或适配层异常时，Agent 返回 `retrieval_error`。
- 异常响应保持统一结构：`trace_id`、`status`、`answer`、`message`、`citations`。

### 3. llm_error 处理

- LLM 调用异常返回 `llm_error`。
- LLM 返回空字符串或纯空格时，也返回 `llm_error`。
- LLM 异常不会导致服务崩溃。

### 4. 幻觉抑制 Prompt

- Prompt 明确要求只基于检索上下文回答。
- 禁止使用上下文之外的常识补全答案。
- 要求关键结论必须标注引用编号。
- 上下文不足时要求直接说明资料不足，不猜测。

### 5. answer 与 citation 一致性

- `AnswerFormatter` 会检查 answer 中的 `[1]`、`[2]` 等引用编号。
- 引用编号不存在时会移除无效编号。
- answer 缺少引用编号但存在 citations 时，会自动补齐 `[1]`。

### 6. 日志链路完善

日志现在记录：

- `trace_id`
- 阶段 `stage`
- `query`
- `retrieval_mode`
- `top_k`
- `retrieval_count`
- `status`
- 错误类型 `error`

## 测试结果

已执行：

```bash
python -m pytest
```

结果：

```text
34 passed
```

新增测试覆盖：

- 低相关检索返回 `no_relevant_context`
- 低相关检索不调用 LLM
- LLM 空输出返回 `llm_error`
- answer 缺少引用时补齐 `[1]`
- answer 含无效引用时修正为有效 citation
- Prompt 包含更强的幻觉抑制规则
- Retrieval Adapter 记录 `[RETRIEVAL_START]`、`[RETRIEVAL_END]` 和 `[RETRIEVAL_ERROR]`
- 检索阶段日志包含 trace_id 和结果数量

## 当前结论

Week 3 Agent 层已完成质量控制、异常兜底、幻觉抑制和引用一致性检查。当前 `agent-dev` 可作为 Week 4 Web 联调和 Demo 测试基线。

## 后续建议

- Week 4 与 Web 层联调 `/api/chat`。
- 准备 Demo 问题集并记录真实 `trace_id`。
- 继续验证 Web 对 `success`、`no_relevant_context`、`retrieval_error`、`llm_error` 的展示逻辑。
- 如时间允许，再做流式输出或由 Web 层 Mock stream 展示。
