# 10-Web SESSION Fact 手工验收

## 前置

- 使用 `SESSION_FACT_ENABLED=true` 与持久 Memory 已启用的本地 Web/Agent 环境。
- 准备两个已认证账号 A、B，和一个匿名浏览器窗口；每个账号各有一个 private chat。
- 在 Network 面板确认浏览器只请求 `/api/chats/:id/memory/facts*`，不接触 `/api/internal/*`，响应不含 user/chat/revision、proposal key 或 source 正文。

## 验收步骤与截图点

1. 账号 A 打开自己的 private chat。刷新页面后，记录 GET `/facts` 返回结果与空/已有的“本会话记忆”面板截图。
2. 在一条当前 revision 的 user message 操作菜单选择“保存为目标”。记录 POST `/proposals` 只含 `source_message_id`、`category`，随后 GET 刷新并显示 PROPOSED 卡片的截图。
3. 点击“确认”。确认按钮请求期间不可重复点击；记录 POST `/confirm` 后卡片进入“本会话记忆”、显示分类和值/到期日的截图。
4. 点击“撤销”。确认请求期间不可重复点击；记录 POST `/revoke` 后该 Fact 从 UI 消失的截图。刷新浏览器，确认它不会重新出现。
5. 使用 Agent 的精确命令产生一条 proposal，完成正常 SSE。记录流结束后的 GET 刷新和 Proposal 卡片截图；随后用“我记住了什么？”提问，记录 assistant 消息上的“来自已确认会话记忆”静态标签。该标签不得作为 citation，且不得显示 Fact ID。
6. 对一条包含 `password`、银行卡号或住址的 user message 执行手动保存。记录“该内容不能保存为记忆”提示；不得出现敏感原文、Fact ID 或 source ID。
7. 在流式回答过程中点击停止，或断开网络。确认没有因取消/错误而触发 Fact 刷新或制造新的 Fact，并记录 Network/界面截图。
8. 账号 B 尝试访问账号 A 的 chat URL；匿名窗口访问 A 的 private chat URL；public chat 与匿名 chat 均不显示记忆面板或“保存为记忆”入口。记录隔离截图。

## 记录

- 测试日期、环境提交、账号 A/B、chat ID（仅保存于受控测试记录，不放入 issue/公开日志）：待填写。
- 录屏或逐步截图路径：待填写。
- 结果：待执行。此文档是可复现的手工验收脚本，不代表自动化 E2E 已通过。
