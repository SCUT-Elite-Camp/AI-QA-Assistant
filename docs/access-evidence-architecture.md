# 访问边界与证据链路

更新：2026-10-09。适用分支：`integration/agent-demo-access-evidence`，基线为 #63 的 `cdbe02b`。

## 解决什么问题

检索命中不等于有权读取；引用编号存在不等于原文仍然有效；曾经保存的回答也不能成为撤权后的绕行入口。本实现把这些检查从单次检索扩展到生成、持久化、历史、记忆与原文读取。

```text
浏览器会话 → Web/BFF 确认当前用户与资源角色
                       ↓ 可信内部请求，浏览器不能提供授权上下文
Agent 请求级 AccessGuard → 当前来源授权 ∩ 用户选择范围
                       ↓
Toolset 召回/读取 → 核对原文、版本、哈希 → Evidence
                       ↓ 每次模型调用前重新校验
生成与引用检查 → evidence.provenance.v1
                       ↓
BFF 再校验 → 保存服务端答案与证据 → 再校验 → 向浏览器释放
                       ↓
历史 / 收藏 / 分支 / Memory / 引用 Reader 继续检查当前权限与版本
```

## 各层边界

| 层 | 权威输入与职责 | 不允许的捷径 |
| --- | --- | --- |
| Web/BFF | Cookie 会话、数据库用户状态、chat/topic 当前角色；写操作 CSRF；构造内部上下文 | 信任浏览器的 `X-User-ID`、角色、历史 assistant 文本或 Memory |
| Agent | 请求级 `AccessGuard`；工具执行前后、模型调用前、最终释放前校验；诊断与 Memory 决策使用 ContextVar | 共享可变的上一请求状态；把冻结 manifest 当永久授权 |
| Toolset | 强制授权范围；返回可核对的原文及来源元数据；私有服务调用禁止跳转 | 由模型自行决定 owner/KB；把企业 doc ID 当个人库文档 ID |
| 数据源/存储 | 原文版本与正文哈希；本地 ACL；源站原生权限；附件远端元数据 | 用旧索引文本绑定新正文；用本地管理员身份绕过源站权限 |
| 衍生数据 | Answer、Snapshot、Fact、Topic 摘要继承所有来源依赖 | 将失效回答复制为无来源新消息；将未知来源的旧摘要继续送入模型 |

内部 Agent API 使用 Bearer `AGENT_API_KEY`；`/api/internal/*` 还要求 `X-Agent-Internal-Token`。这些密钥只能存在服务端。直接 Agent API 的 `X-User-ID` 是持共享密钥的可信调用方接口，不是浏览器身份认证方案。

## 三类来源

| 来源 | 当前允许条件 | 版本绑定 |
| --- | --- | --- |
| 企业 Confluence | 当前启用用户、本地 files/file_permissions 授权、显式站点/account ID 绑定、Confluence 原生 read 权限交集 | 文档版本 + 本地权威正文 SHA-256 |
| Personal Library | 当前 owner、个人 KB、`source_scope=personal`、未删除、活动 Version 为 READY，且远端 owner/KB/版本/文件哈希一致 | logical document + active version + 文件哈希；具体证据另有块哈希 |
| 对话/Topic 附件 | 当前 chat/topic 作用域与角色、允许附件集合、未删除/未过期、解析就绪，且 Web/附件服务绑定一致 | attachment ID + evidence version + 实际证据块哈希 |

普通 Chat 已支持单来源和三来源混合。混合请求必须先尝试全部请求来源；缺一个来源的证据不能用其他来源的命中冒充完整答案。来源选择只控制搜索目标，不授予权限。

**Research 当前仅支持企业 Confluence 来源**，不能据三类 Chat 验收宣称 Research 已支持个人库和会话附件。

Confluence 服务凭据用于调用原生权限检查；它们不会自动授权所有本地用户。绑定缺失返回无可访问集合；源站检查不可用返回 503。仅对网络/502/503/504 做一次有界重试，失败仍拒绝。

## 证据与 Reader

Citation 除标题、片段、编号外携带 `evidence_ref`、来源类型、locator、版本、哈希。`evidence.provenance.v1` 记录 `complete` 与 `dependencies`，后者包括全部读取/继承来源，而不只是显示的几条引用。

- 原文入口：`GET /api/messages/{messageId}/evidence/{evidenceRef}`。服务端先验证消息归属，再从已保存 Citation 解析来源；客户端不能提交任意 doc ID 代替它。
- 企业原文必须仍有权限、且与回答时的正文版本匹配；个人库必须仍为同一活动 Version；附件必须仍处于正确 chat/topic 作用域。
- 撤权后历史正文与引用隐藏，收藏过滤失效回答，分支/复制不能洗白来源；恢复授权后同版本资料可再次读取。
- `no_relevant_context` 是不落库的状态提示，不是成功答案；不释放未经核验的模型文本，不写 Fact、Snapshot 或 Topic 来源池。
- 缺来源证明的历史衍生内容按不可信处理，不自动回填 `complete=true`。

入口与错误码见[接入契约](access-evidence-integration.md)。

## Research

Job 绑定创建者；目录、创建、规划、批准、执行、进度、事件、Trace、报告、下载、原文都检查当前身份和来源。批准绑定 Plan version 与 manifest hash，Worker 经共享企业 Toolset 检索/读取冻结来源，而非另建一套近似检索。

每个 Planner/Synthesizer 模型请求和重试边界都有 job-local 权限检查。报告区分 `model` 与 `verified_fallback`，`completed` 与内容 `complete/degraded` 分开。完整原文记录和正确 Citation 不保证问题覆盖或回答质量，仍须单独评测。

Wiki 页面的标题、摘要及关系元数据目前缺完整访问依赖证明。保留 #63 的 Wiki 路由代码，但运行时隔离这些导航工具；不要为了演示打开开关绕过边界。恢复条件是导航数据本身也继承并校验全部原始来源。

## 数据模型与迁移

- Web migration `0015_evidence_lineage.sql` 给 `chats`、`topics`、`memory_snapshots`、`memory_facts` 增加 `evidence_provenance`。消息证明保存在 `messages.parts`。
- Attachment Store 与 Web 同步 `chat_id`/`topic_id` 作用域绑定；上传后绑定和提升 Topic 作用域不是只修改前端选择状态。
- Drizzle `mode: timestamp` 的附件过期时间单位为 epoch **秒**；不要与 Memory DTO 的毫秒字段混用。
- 移植已有数据库前先备份；新隔离数据库应执行完整 journal 到 0015，而不是只手工增加最后几个字段。

## 不在本轮结论中

这不是完整生产安全审计，也不代表所有角色、所有文件格式、浏览器布局与重复稳定性都已验收。冻结 Confluence 正文可以复现质量结果，但源站权限校验不等于已同步源站最新正文。运行与验收边界见[运行手册](access-evidence-runbook.md)和[交接报告](pr63-integration-acceptance.md)。
