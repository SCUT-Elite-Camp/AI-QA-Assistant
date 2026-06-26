# vibe 开发指南

本文档说明使用 vibe 方式推进 Q1 Web 层时，每轮应该怎么拆任务、改代码、验收和更新文档。

## 每轮 vibe 的输入

开始前先明确四件事：

1. 本轮属于哪个阶段；
2. 本轮只完成哪个小功能；
3. 本轮会不会改变接口契约；
4. 本轮如何验收。

推荐每轮只做一个明确目标，例如：

- 完成 `/api/v1/chat` Mock；
- 完成 citations 展示；
- 完成 SSE token 解析；
- 完成 `timeout_error` 映射；
- 完成 Spring Boot BFF 到 Agent 的转发。

## 每轮 vibe 的执行顺序

1. 读 `agent.md`。
2. 对照 `q1-three-phase-plan.md` 找到当前阶段。
3. 如果涉及接口，先看 `api-contract.md`。
4. 修改代码。
5. 运行可用测试。
6. 手动验证 Demo 场景。
7. 更新 `vibe-log.md`。
8. 如果接口或范围变化，同步更新相关文档。

## 前端任务验收方式

Vue 每次修改后至少检查：

- 页面能打开；
- 控制台没有明显报错；
- 可以输入并发送问题；
- loading 能开始和结束；
- 错误后输入框恢复；
- citations 展示正确；
- 复制和清空可用。

## BFF 任务验收方式

Java Spring Boot BFF 每次修改后至少检查：

- `/api/v1/chat` 可访问；
- 空输入返回稳定错误；
- 正常 Mock 返回 `success`；
- 每次响应都有 `trace_id`；
- 日志包含 `trace_id`；
- 异常能映射成统一 `status`；
- 与 `api-contract.md` 字段一致。

## 联调任务验收方式

真实 Agent 联调时至少检查：

- BFF 能连通 Agent；
- JSON 完整答案能展示；
- SSE token 能逐步展示；
- done 事件能结束 loading；
- Agent 异常能映射为 Web 状态；
- citation 能展示；
- Mock 兜底仍可用。

## 每轮结束要写什么

更新 `vibe-log.md`：

- 日期；
- 本轮目标；
- 改了哪些文件；
- 验收结果；
- 遇到的问题；
- 下一步。

如果修改了接口，更新 `api-contract.md`。

如果改变了阶段计划，更新 `q1-three-phase-plan.md`。

如果 Demo 范围变化，更新 `july-demo-delivery-scope.md`。

## 不建议在 Q1 vibe 中做的事

- 直接让 Vue 连接 Agent；
- 直接让 Vue 连接 Redis 或向量库；
- 在 Web 层实现文档解析和向量化；
- 先做登录、权限、多轮对话等加分功能；
- 改接口但不更新文档；
- 让 Mock 响应结构和真实接口不一致。

