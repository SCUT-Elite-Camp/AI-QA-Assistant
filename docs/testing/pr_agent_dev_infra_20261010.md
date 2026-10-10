# PR Title

feat(agent): integrate CP2 research, native source access and verified evidence workflows

# PR Description

## Summary

将 `agent-dev-infra` 合并到 `agent-dev`，交付当前 Agent CP2 问答与 Deep Research 版本，以及与 Web/BFF、检索和证据读取的整合。普通问答和研究报告使用当前授权来源生成，引用绑定真实原文与版本；本轮进一步解决英文查询、跨文档比较、日期判断、状态表格和证据不足回答中的质量问题。

## Changes

- **CP2 问答与研究链路**：继承会话记忆、QueryPlan、有界工具循环及 Research 规划、审批、执行、进度、报告、追问和下载链路，并保留既有前端主题、推理过程、引用 Reader 和 Personal Library 整合。
- **来源访问与证据约束**：浏览器身份来自服务端会话；Confluence 授权取本地 ACL 与源站原生读取权限交集。模型调用、答案释放、历史衍生内容、Memory 和 Reader 持续检查当前权限及版本/hash，未知来源隔离。Research 仍仅接受企业 Confluence。
- **英文与检索质量**：英文问题保持原语言；明确选定来源的事实、状态和比较请求先检索并执行有界原文读取，避免用文档摘要代替正文或遗漏比较另一侧。
- **结构化事实与引用**：从真实表格解析数量、差值、状态和计划时间；保留重复 Goal ID 的独立能力，空状态输出 `not recorded`。区分事件日期与导出时间、计划与已交付能力、历史会议问题与当前状态。精确引用保留 anchor 与邻段上下文的区别。
- **证据不足与评测**：不足时不替换成其他模块数字；引用支持实际检查到的来源。评分器严格验证 JSON、分数和检查项一致性，仅对结构异常进行一次重试；原始负评分和历史失败保留。
- **文档与测试基准**：同步接入契约和运行手册；为更新后的 CP2 Goals version 18 新建三道英文 v2 回归题，保留历史测试集和成绩；提交结果摘要与证据索引。

## Validation

| 检查 | 结果与范围 |
| --- | --- |
| 最终 Agent 完整本地回归 | **887 passed**，3 项依赖弃用警告；包含隔离单元与契约测试 |
| 本轮剩余英文在线用例 | **14/14 累计运行及机器质量通过**；真实模型 `qwen3-235b-a22b-instruct-2507`，实际检索、parser/embedding 和原生权限 |
| 定向续跑方式 | 前一阶段保留 11 个通过坐标；状态路由修复后只补测剩余 3 个，3/3 通过。不是最终代码上的 14 次重新全跑 |
| 成功答案的来源核对 | 助手逐项复核 14 份答案；摘录有效率均为 1.0，越界引用为 0；不等同于独立人工评审 |
| 真实权限与 BFF 链路 | **16/16**：ACL 拒绝、跨用户报告/事件/Reader、匿名访问、会话原文读取及缺失 CSRF |
| 来源版本复核 | **14/14** 未变化；代码、题目、BM25 和绑定配置与最终补测冻结条件一致 |

本轮没有新增前端生产代码修改，未重新进行完整浏览器视觉/交互、全量 G1/G2 或并发性能验收。此前阶段的测试与分数保留各自条件，不合并宣称为同一版本全量通过。测试题参与过修复，属于回归集；机器裁判与生成使用同一模型，独立人工验收仍待完成。

## Review references

- [剩余修复及最终复测](docs/testing/remaining_repairs_20261010.md)
- [结果摘要与逐坐标索引](docs/testing/evidence/remaining-20261010/summary.json)
- [前一轮高风险修复](docs/testing/high_risk_repairs_retest_20261009.md)
- [测试条件核对](docs/testing/high_risk_conditions_repeat_20261009.md)
- [访问与证据架构](docs/access-evidence-architecture.md)、[接入契约](docs/access-evidence-integration.md)、[运行手册](docs/access-evidence-runbook.md)

凭据、运行数据库、源站导出、完整私有正文和原始回答轨迹不包含在本次提交中。复现真实验收需要运行手册所列的私有配置与授权来源。
