# 10-Web SESSION Fact 体验

## 目标、前置与施工位置

只消费 `09-Web` 已完成的服务器 Fact API，让用户看见、确认、拒绝、撤销或手动提出 SESSION Fact。
不创建/修改 server routes，不读取 Agent `memory_decision`，不显示 Snapshot，也不增加 USER/跨会话记忆。

前置：`01`、`09a-Web`、`09-Agent`、`09-Web` 均审查通过。后续：`12`、`13`。负责人：Web。

```text
唯一工作区：D:\project\AI-QA-Assistant
唯一分支：web-dev
```

允许修改：

- 新建 `web/src/components/chat/memory/FactProposalCard.vue`
- 新建 `web/src/components/chat/memory/SessionFactPanel.vue`
- 新建 `web/src/composables/useSessionFacts.ts`
- `web/src/pages/chat/[id].vue`
- `web/src/components/chat/message/MessageActions.vue`（仅 user message 的手动保存入口）
- `web/src/composables/useChatActions.ts`（仅接入刷新时机）
- 新建 `web/tests/manual/10-fact-web-experience.md`
- 仅为 TypeScript 类型共享而修改 `web/src/types/**`；若该目录不存在，停止并在交接中报告实际类型落点

禁止修改 `web/server/**`、Agent、数据库 schema/migration、公开 ChatResponse、主题/收藏/Deep Research UI，
以及任何 localStorage/sessionStorage 中的 Fact 存储。当前项目没有 Vue component test harness；本单元不得
为了测试临时新增前端测试依赖。

## 固定 API 输入、UI 状态与输出

唯一数据源是 `09a-Web` 冻结的四条 server API。每次读取 `GET /api/chats/:id/memory/facts` 后，前端只
保存当前组件内的 `FactView[]`；离开 chat 或 `chatId` 改变时清空。不得从 SSE、Agent decision、浏览器缓存
或 URL query 恢复 Fact。

| 用户动作 | HTTP 调用 | 成功后的 UI | 失败后的 UI |
| --- | --- | --- | --- |
| 初次进入、正常 SSE 完成、confirm/revoke/proposal 完成 | `GET /facts` | 用服务端结果整体替换本地状态 | 保留最近成功结果并显示通用失败提示 |
| 手动保存 | `POST /proposals` body `{ source_message_id, category }` | 重新 GET；出现 PROPOSED 卡片 | 显示 `fact_sensitive` 的统一文案“该内容不能保存为记忆”，其他 code 显示“记忆操作失败” |
| 确认 | `POST /:factId/confirm` 空 body | 重新 GET；由 PROPOSED 移入 Confirmed 面板 | 重新 GET，不乐观更新 |
| 拒绝/撤销 | `POST /:factId/revoke` 空 body | 重新 GET；从 UI 消失 | 重新 GET，不乐观更新 |

只有已认证的私有 chat 显示 UI。匿名、公开 chat、`session_fact_disabled` 或 404 时不显示面板/手动入口；
不把禁用原因、Fact ID、source ID 或敏感原文呈现给用户。请求进行期间，对应按钮 disabled；同一事实不允许
重复点击。卡片显示 category、人类可读 value、已确认状态和到期日；仅 Confirmed、未过期 Fact 进入
“本会话记忆”面板。显示确定性 recall 的 assistant 消息时只展示静态标签“来自已确认会话记忆”，不能作为
RAG citation，不能显示 Fact ID。

## 有序实施步骤

1. 在 `useSessionFacts.ts` 定义 `load/propose/confirm/revoke`，将 HTTP code 映射为上述有限 UI 状态；
   一律以成功后重新 GET 作为真相，不写 localStorage。
2. 在 chat 页面以 chat ID 和认证状态为依赖，在首次进入和 `useBffChat` 报告的**正常**流完成后调用
   `load`；取消、错误和重连过程不得把 Fact 状态伪装为成功刷新。
3. 新建 Proposal card 与 Confirmed panel。Proposal card 只可确认/拒绝；Confirmed panel 只可撤销；
   两者都不能编辑 value/category/scope/日期。
4. 在 MessageActions 只为当前 chat 的 user message 提供“保存为记忆”；类别由受控枚举选择，提交的
   唯一消息字段是 message ID。不得为 assistant、tool、citation 或历史已删除消息展示入口。
5. 写入手工验收脚本，记录测试账号/匿名账号、chat ID 隔离、正常/取消 SSE、敏感拦截与显式 recall 标签。
   不存在自动化组件测试时，这份可复现脚本是验收证据，不得声称 E2E 自动化通过。

## 测试、检查与停止条件

```powershell
Set-Location D:\project\AI-QA-Assistant\web
pnpm run typecheck
pnpm run lint
pnpm exec vitest run tests/routes/factLifecycle.test.ts tests/integration/chat-memory-flow.test.ts
```

随后严格按 `web/tests/manual/10-fact-web-experience.md` 完成一次录屏或逐步截图，至少覆盖：手动 proposal、
Agent proposal 显示、confirm、revoke、刷新、跨 chat/匿名隔离、敏感拒绝、SSE 取消和 recall 标签。

完成条件：命令成功、手工证据齐全、diff 只含允许路径、浏览器未接触内部 decision 或权威字段。
停止并报告：09-Web API/FactView 未冻结、现有 chat 页面无法明确辨别正常 SSE 完成、需要 server 修改、
需要新增前端测试依赖，或无法判定 chat 是否已认证/私有。交接给 12 的内容是 UI 状态机、错误文案、
手工验收记录和已运行命令。
