# 09a Fact 去重与幂等 HTTP 合同（先行单元）

## 目标

先于 `09` 冻结并实现 Fact proposal、confirm、revoke 的去重和幂等合同，使后续生命周期/Agent
proposal 接入不再自行选择“返回 409 还是幂等成功”。本单元只实现 Repository/HTTP 合同，不生成
Agent Fact proposal、不做 UI；confirm/revoke 仍严格按本合同更新既有 Fact 状态。

前置：`03`、`04`、`07`、`08`。负责人：Web + Agent。后续：`09`、`10`、`12`。

施工位置：Web Repository/HTTP 合同只在 `D:\project\AI-QA-Assistant`（`web-dev`）实施；
Agent 仅审查 `FactProposal { category, value, sourceMessageId }` 的字段约定，不修改 Agent 源码。

## 固定去重规则

proposal 的 `proposal_key` 为 UTF-8 文本以下字段以 NUL 分隔后计算 SHA-256 的小写十六进制：

```text
chat_id \0 history_revision \0 source_message_id \0 category \0 normalized_value
```

`normalized_value` 的规则：Unicode NFC、trim、连续空白折叠为一个空格；除此之外不改写大小写或中文文字。Repository 写入时在 `UNIQUE(chat_id, history_revision, proposal_key)` 冲突下读取并返回既有 Fact。

若同 key 的既有 Fact 为 PROPOSED 或 CONFIRMED，proposal 返回既有对象和 200；若为 REVOKED，返回既有 REVOKED 对象和 200，不创建新 Fact。用户若想重新记忆，必须从新的 source message 发起，避免把已拒绝事实无声复活。

## 固定状态和响应规则

| 请求 | 当前状态 | 新状态 | HTTP | 返回 |
| --- | --- | --- | --- | --- |
| proposal | 无 | PROPOSED | 201 | 新 Fact |
| proposal | 任意同 key | 不变 | 200 | 既有 Fact |
| confirm | PROPOSED | CONFIRMED | 200 | 更新后 Fact |
| confirm | CONFIRMED | 不变 | 200 | 既有 Fact |
| confirm | REVOKED | 不变 | 409 | `fact_revoked` |
| revoke | PROPOSED/CONFIRMED | REVOKED | 200 | 更新后 Fact |
| revoke | REVOKED | 不变 | 200 | 既有 Fact |

`confirmed_at` 只在首次 confirm 写入；`expires_at` 也在首次 confirm 根据类别设置。revoke 不清空 value/source，以便受控审计，但 Resolver 永远忽略 REVOKED。

## 实施步骤

1. 在 `memoryRepository.ts` 以 transaction 实现 proposal upsert/read、confirm、revoke；所有查询必须带 actorUserId、chatId、historyRevision。
2. 固定 Agent 的 FactProposal 字段为 category/value/sourceMessageId；Web 计算 proposal_key，Agent
   不生成 key。实际 Agent proposal 生成只由后续 `09` 实施。
3. API error body 固定为 `{ "code": "fact_revoked", "message": "..." }`；UI 按 code 显示可理解提示，不以字符串匹配。
4. Confirm/revoke UI 禁用重复点击，但正确性依赖服务端幂等而非 UI。

## 验收

- 并发两次同 proposal 只创建一行。
- 双击 confirm/revoke 的最终状态正确，时间戳不被重复改写。
- REVOKED 不能重新 confirm；同源同值不能无声重新 proposal。
- A 的 Fact ID 不能被 B 调用；所有断言覆盖过期 Fact。
