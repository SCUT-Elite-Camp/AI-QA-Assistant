# 07 成功回合后的版本化增量压缩

## 目标

在助手消息成功持久化后，创建新版本 Snapshot；压缩失败不影响本轮回答，下一次成功回合可补偿。此单元不引入 Redis、MQ 或新队列。

前置：`02`、`03`、`04`、`06`。负责人：Web + Agent。后续依赖：`08`、`12`。

## 触发和执行时序

Web 的 `onFinish` 先按 `02b` 写入成功助手消息并获得其 sequence。随后 BFF 读取当前 revision 的 active Snapshot 与消息，并调用唯一的 `POST /api/internal/memory/compaction-plan`；Agent 返回纯数据计划，Web Repository 在事务内归档旧 Snapshot、写入新 ACTIVE Snapshot。

不能在 Agent 回复尚未成功持久化前生成 Snapshot；Agent 错误、浏览器取消、DB 写入失败、错误占位回答都不触发。

## 压缩规则

1. 查询 `sequence > active.covered_to_sequence` 的当前 revision 消息；无 active Snapshot 时从 sequence=1 开始。
2. 去掉末尾未配对用户消息，保留最近 8 条完整原文为 Tail。
3. 其余为 coverable 区间；当其至少 12 条或估算输入超过 1000 tokens 时触发，否则返回“不压缩”。
4. 新 summary 只基于旧 summary 与 coverable 区间，采用结构化、规则式、有长度上限的增量摘要；只处理 `user/assistant` 的完整消息。调用 `09` 固定的 `isSensitiveMemoryValue(text)`；命中时整条消息不进入 summary。不得调用 LLM。
5. 新 Snapshot 记录 `history_revision`、`version=old+1`、覆盖首尾 sequence/message ID。旧 ACTIVE 仅在 `id/version/status` 都匹配时归档；冲突则重新读取后有限重试，仍失败则安全放弃。

## 允许修改范围

- Web：`web/server/utils/memoryRepository.ts`，新建内部 Memory route/client 与测试。
- Agent：新建 `agent/agent/memory/compaction_planner.py`、内部路由/DTO、tests。
- 必要的 config/docs；不直接修改公开响应。

## 测试与验收

- 11 条 coverable 不建 Snapshot；12 条建 version=1。
- 新版本覆盖旧版后，旧 ACTIVE 变 ARCHIVED，新版唯一 ACTIVE。
- 两个并发压缩请求不会产生两个 ACTIVE。
- 重启/再次 resolve 可由 Snapshot + Tail 重建；当前 query 不在 Snapshot Tail 中重复。
- 人为使 compaction plan/DB 更新失败时，聊天结果仍成功、下一回合可再次尝试。

## 交接

输出 revision/version 失效规则给 `08`，输出压缩指标给 `11`。不得为“异步”新增未经批准的后台任务框架。
