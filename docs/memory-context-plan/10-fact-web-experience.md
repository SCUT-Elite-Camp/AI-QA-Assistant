# 10 Fact 确认、撤销与回忆的 Web 体验

## 目标

让用户知道系统提议保存什么、可以拒绝/确认/撤销；避免无感采集个人信息。此单元只实现 SESSION Fact UI，不增加跨会话开关。

前置：`01`、`09`。负责人：Web。后续依赖：`12`、`13`。

## UI 与 API 行为

1. 初次进入 chat 页面和本轮正常 SSE 流结束后，前端固定调用 `GET /api/chats/:id/memory/facts`。只根据该服务端响应，在对应 source user message 或对话区域展示 `PROPOSED` 的“建议记住”卡片；绝不读取 Agent `memory_decision`、SSE data event 或浏览器缓存。卡片展示 category、人类可读 value、到期提示、确认/拒绝按钮。
2. 点击确认仅调用 confirm API；点击拒绝固定调用 revoke API。禁止前端乐观地把 PROPOSED 当作已记忆。
3. 新增“本会话记忆”轻量面板：只列 `CONFIRMED`、未过期的 Fact；每项有撤销。不可显示 Snapshot 摘要。
4. 用户可以从自己的历史消息主动选择“保存为记忆”；前端只提交 message ID、category，服务端重新读取正文与归属。
5. 显式回忆回答在消息 UI 中可显示“来自已确认会话记忆”，但不可伪装为 RAG citation，也不可泄露内部 Fact ID。

## 允许修改范围

- 新建 `web/src/components/chat/memory/*`
- 修改 `web/src/components/chat/message/MessageActions.vue`（只增加用户消息的手动保存入口）
- 修改相关 composable，例如 `web/src/composables/useChatActions.ts`
- 新建 server routes 与前端测试；不改无关主题/收藏功能。

## 安全和可用性规则

- 未登录状态不显示持久 Fact UI。
- 请求中按钮失效并显示明确状态；失败后重新读取服务端状态，避免重复确认。
- UI 不提供 USER/跨会话范围选择；不能把 Fact 复制到浏览器 localStorage。
- 不显示敏感拦截原因的原文；统一提示“该内容不能保存为记忆”。

## 验收

- PROPOSED 只能在确认后进入已确认面板。
- 刷新页面后 Confirmed Fact 仍从服务端加载；撤销后不再显示或进入 prompt。
- 不同 chat 的 Fact 面板隔离；公开 chat 页面没有 Fact 面板。
- `pnpm run typecheck`、`pnpm run lint` 成功；手动录屏覆盖确认、拒绝、撤销和显式回忆。

## 交接

提交 UI 状态机、错误文案和 API 调用说明给 `12`。若无可靠前端测试框架，至少提供可复现的手工验收步骤，不得声称 E2E 已通过。
