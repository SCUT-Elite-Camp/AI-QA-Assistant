# 01 Web 身份与 chat 访问控制

## 目标

使 Web BFF 成为 Memory 的可信身份边界：任何发送、读取 Fact、确认 Fact、编辑、重生成或删除 Memory 的请求，都必须由服务器会话推导用户身份并验证 chat 所有权。

前置：`00`。负责人：Web。后续依赖：`02`、`03`、`04`、`10`。

## 当前入口与允许修改范围

- `D:\project\AI-QA-Assistant\web\server\utils\session.ts`
- `D:\project\AI-QA-Assistant\web\server\routes\api\chats\[id].post.ts`
- `D:\project\AI-QA-Assistant\web\server\routes\api\chats\[id].get.ts`
- `D:\project\AI-QA-Assistant\web\server\routes\api\chats\[id].delete.ts`
- `D:\project\AI-QA-Assistant\web\server\routes\api\chats\messages\[id].delete.ts`
- 新建 `D:\project\AI-QA-Assistant\web\server\utils\chatAccess.ts` 及其测试。

现有 `POST /api/chats/[id]` 只按 chat ID 查询，未在发送前校验 owner；`[id].get.ts` 对未登录状态有本地宽松读取分支。持久 Memory 上线后，所有会修改或读取私有 Memory 的路径不得保留该宽松分支。

## 不变量

- 浏览器 body/query/header 中出现的 `userId` 一律忽略；不得新增此公开字段。
- `actorUserId` 只能来自 `useUserSession(event)`，再与 `chats.user_id` 比对。
- 未登录用户可继续普通聊天，但 `PERSISTENT_MEMORY_ENABLED` 对其为 false；不能创建、读取、确认或回忆 Fact。
- 公开 chat 只可公开消息内容；绝不公开 Snapshot、Fact 或其元数据。
- 会话密钥不能使用生产默认值。非开发环境缺少 `SESSION_SECRET` 必须拒绝启动或拒绝鉴权路径。

## 实施步骤

1. 新建 `chatAccess.ts`，导出 `requireActor(event)`、`requireOwnedChat(event, chatId)`。前者在无登录用户时固定返回 401；后者在一次查询中校验 `chat.id` 与 `chat.userId`，缺失或非本人一律返回 404，不能暴露 chat 是否存在。
2. 替换上述聊天路由内重复的 `session.data.user?.id || session.id!` 所有权判断。读取公开 chat 可保留展示逻辑，但必须返回 `isOwner=false`，且 Fact API 不得复用公开读取权限。
3. 在发送路由最早位置调用 `requireOwnedChat`，然后才读取 body、写用户消息或请求 Agent。
4. 新增环境变量约定：Web 使用 `AGENT_BASE_URL` 与 `AGENT_INTERNAL_TOKEN`；不得硬编码 `127.0.0.1` 为安全边界。真实值写 `.env`，示例只写 `.env.example`（无密钥）。
5. 将所有将来的 `/api/chats/[id]/memory/*` 路由建立在该 helper 上。

## 必测场景

- A 用户不能 POST、DELETE、编辑、确认或读取 B 的私有 chat/Fact，响应不泄露 B 的数据。
- 未登录用户对普通 chat 的既有行为不被破坏，但请求 Fact 路由得到拒绝或明确禁用响应。
- 伪造 body 中的 `userId=B` 不改变实际 actor。
- 生产配置缺少 `SESSION_SECRET` 时不会静默使用默认密钥。

## 完成与交接

完成条件：所有 Memory 路由复用唯一所有权 helper；现有聊天路由的发送入口已校验 owner。交接 `actorUserId + owned chat` 给 `02` 和 `04`。若团队决定允许匿名持久记忆，必须先补充匿名身份生命周期与删除策略，不能自行放宽。
