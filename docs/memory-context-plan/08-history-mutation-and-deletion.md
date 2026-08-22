# 08 编辑、重生成、分支与删除的 Memory 一致性

## 目标

保证 Memory 永不引用已编辑、已重生成或已删除的历史。采用 chat `history_revision` 失效模型，而不是局部修改摘要文本。

前置：`02`、`03`、`04a`、`07`。负责人：Web。后续依赖：`12`、`13`。

施工位置：`D:\project\AI-QA-Assistant`（`web-dev`）。当前 Web 实现已完成，本单元默认只审查
Web 的 revision/delete 事务与既有 internal reset 调用；不得在 Agent worktree 修改或新增 reset 路由。

## 实施规则

### 编辑用户消息 / 重生成助手消息

在 `web/server/routes/api/chats/messages/[id].delete.ts` 的删除事务中：

1. 按 `sequence` 找到变动点并删除该点之后的消息（保持现有 edit/regenerate 语义）。
2. 同事务将 chat 的 `history_revision` 加一；后续新消息带新 revision。
3. 旧 revision Snapshot 不删除历史记录，但 Resolver 必须忽略；旧 revision 的所有 SESSION Fact 在同一事务中转为 `REVOKED`，不得进入新 revision。
4. `04a` 已负责移除无鉴权 `DELETE /api/chat/memory/{session_id}` 并实现受 token 保护的 private
   reset endpoint。本单元只在数据库事务提交后通过既有 BFF client 调用该 endpoint 清理旧进程短窗；
   调用失败不得影响持久 Memory 一致性。不得改 Agent 路由、依赖或 lifespan。

### 分支 chat

新 branch 是新 `chat_id`、revision=1、sequence 从 1 开始。默认不复制父 Snapshot 或 Fact；若 UI 复制消息，必须逐条按新 chat 分配 sequence。不要以父 chat 的 `session_id` 调用 Agent。

### 删除

删除 chat 时，通过外键删除 Snapshot 和 SESSION Fact；删除前后均不能把其他用户的事实删掉。无鉴权的
Agent `/chat/memory/{session_id}` 已由 `04a` 删除；本单元只验证 Web 不再调用它，而是在提交后调用既有
private reset endpoint。

## 允许修改范围

- `web/server/routes/api/chats/messages/[id].delete.ts`
- `web/server/routes/api/chats/[id].delete.ts`
- `web/server/routes/api/chats/[id]/branch.post.ts`
- `web/server/utils/memoryRepository.ts` 和相关 tests

禁止修改任何 Agent 文件；reset endpoint 的 token、共享 `get_agent()` dependency override 和路由删除只由 `04a` 的 tests 验收。

## 验收

- 编辑一个已被 Snapshot 覆盖的旧消息后，下一轮不会读旧 summary/Fact。
- 重生成后不引用旧助手答案。
- branch 的 Fact、Snapshot、sequence 与父 chat 完全隔离。
- 删除 chat 后没有残留 Snapshot/Facts，删除不存在/非所有者 chat 不影响任何数据。
- Web 测试断言编辑、分支、删除事务提交后只调用既有 private reset client；`04a` 已有的 dependency override
  测试证明共享 `get_agent()` 注入。编辑、分支、删除和 reset 均不创建或清理 Deep Research Job。

## 停止条件

若现有 UI 的“编辑后重新发送”流程不清楚，先写端到端测试或手工复现说明；不要猜测其消息删除顺序。
