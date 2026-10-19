# MiniCheck 结构化上下文实际核验

2026-10-19，按用户要求，对[输入构造组件](../../../agent/docs/verification_context.md)输出进行真实分类推断。
未修改组件、断言、标签、阈值、模型或在线放行流程。

## 结论

两轮共同完成推断的 114 对英文样本中，**误放行仍为 3/76，误拒从 3/38 降到 2/38**。
只有 `EN-Q10-1` 改善，其余五条原误判保持原判定。
另外 12 对结构化输入超过 512 token，未执行分类器，不计作正确拒绝或语义核验通过。

因此，本次没有证明结构化上下文降低了错误断言的放行风险。
它改善一条误拒，同时降低覆盖率并增加本次批量推断成本，尚不足以据此启用线上拦截。
继续保留 MiniCheck 选型，但当前输入策略仍需改进和新的独立验证。

## 实验方法

同一批 126 对英文断言/原文；gold 由 Codex 逐条核对，保留原标签和理由。
原开发、留出和回归分组沿用历史标识，但这些题已经被看过，本轮全部属于已见样本复测。
它们是相对冻结原文的支持关系测试，不是自然生成错误的发生率、最新业务规范或独立人审结论。

执行两轮：

1. 原片段基线：使用冻结的 quote 拼接上下文，126 对均推断。
2. 结构化上下文：用相同断言及 `bound-structure.v1` 构造结果，114 对推断，12 对跳过。

两轮输入均在第一次推断前冻结到 `frozen-inputs.json`，结构化输出逐条与上轮准备结果核对一致。
先运行基线，再运行结构化轮次；同一进程内使用同一已加载模型和一次公开合成句预热。
没有改写断言直到通过、裁掉超长内容、增加关键词规则、调用外部 judge 或调分类阈值。

模型为真实本地 `lytang/MiniCheck-DeBERTa-v3-Large`：

```text
revision: 2f2d01a54fa022a7ffadb76260e1ea8bc88c82bb
weight SHA-256:
32ced784f4831d5f324a072e43b96d4072cac4bf41042bc42243605ffbbccbdf
dataset SHA-256:
8f03ac6b631ff794d18b7c546e906e864108342311a9a8e8ce18dfe9885af3c1
```

Windows CPU、float32、4 线程、batch=4，Torch 2.12.1+cpu、Transformers 5.17.0。
输入使用官方 EOS 拼接方式，固定训练 argmax 决策；加载诊断无缺失/多余/不匹配参数或错误。
分类输出只有 supported/not_supported，不伪造矛盾与证据不足的三态预测。
私有分类概率仅留离线产物，不是答案模型自评或正确率。

## 可比结果与未核验样本

| 指标 | 原片段基线 | 结构化上下文 |
| --- | --- | --- |
| 全部计划样本 | 126 | 126 |
| 实际完成分类 | 126 | 114 |
| 未核验 | 0 | 12 |
| 两轮共同可比样本 | 114 | 114 |
| 共同样本误放行 | 3/76（3.95%） | 3/76（3.95%） |
| 共同样本误拒 | 3/38（7.89%） | 2/38（5.26%） |

新跑的原片段基线在全部 126 条上仍为误放行 3/84、误拒 3/42，与之前英文轮次的
126 个标签完全一致。不能拿基线 126 条与新轮次 114 条直接比较一个合并准确率。

12 条未核验是 `EN-Q19-1`～`EN-Q19-6`、`EN-Q20-1`～`EN-Q20-6`，
都来自同一份 Architecture Decision Records，完整输入为 941～950 token。
其中 **4 条 gold 有支持、4 条矛盾、4 条证据不足**。
它们没有模型判定，不填 0 分、支持或拒绝来补齐结果。

若按“任何不支持或未核验均不放行”的决策计算，原方案 42 条正确断言有 3 条未获放行；
新方案有 2 条实际误拒加 4 条未核验，共 **6/42** 未获放行。
这是断言层面的可用性，不是整条实际答案的拒答率；这些构造病例不是完整自然回答。

## 哪些变化、哪些仍错

唯一改善 `EN-Q10-1`：

> Provenance contains read and inherited dependencies, including ones not displayed as citations.

原文明确 provenance 不限于可见引用；加入标题和同结构段落组的背景后，
判定由 not_supported 变为 supported。输入从 103 token 增为 317 token。
这只能证明本次完整输入变化改善该病例，不能确定是标题、背景、来源标记或其中某个词单独造成。

仍误放行三条：

| ID | 英文断言 | 原文核对 |
| --- | --- | --- |
| EN-Q11-3 | The exporter rewrites Confluence page bodies. | exporter 明确为 read-only，写入索引/本地投影属于其他操作 |
| EN-Q16-3 | The stated project-document update deadline is two days, not three days. | 项目文档更新期限是 3 天，2 天属于格式纠正提醒 |
| EN-Q18-3 | The Agent health endpoint proves retrieval resource readiness. | health 只证明进程存活，ready 才报告资源就绪 |

仍误拒两条：

| ID | 英文断言 | 原文核对 |
| --- | --- | --- |
| EN-Q10-2 | Reader rechecks current permissions, body version, hash and the original excerpt. | Reader 的 permission、body version、hash、excerpt 检查均有记载 |
| EN-Q16-2 | Corrections must be made within two days of a formatting correction reminder. | 格式纠正提醒行明确要求两天内修改 |

Codex 再次检查了这六条在新旧完整输入中的支持关系，保留原 gold。
新上下文没有为三条错误断言增加成立依据；两条正确断言的原支持也仍然存在。

当前构造器没有复现此前人工聚焦诊断的全部改善，原因是两种输入策略不同：
这些冻结病例的绑定经常是**整段或整表**，程序必须保留锚点覆盖的全部内容，
不会因为已经知道该题错误，就从绑定中只留下某个句子或某一行。
本轮三个误放行输入仍保留完整段落/表格，并附加了标题和邻接背景。
这保留了可追溯性，但没有消除模型的关系混淆；不能把上轮人工诊断当成本组件的通过成绩。

## 耗时与输入限制

| 本次实际测量 | 原片段基线 | 结构化上下文 |
| --- | --- | --- |
| 计入质量的 forward 批次 | 32 | 29 |
| 累计分类 forward | 39.90 s | 71.00 s |
| 该轮循环耗时（含权限/文件检查、编码、写结果） | 55.47 s | 87.85 s |

这不是单请求 p50/p95，也不是线上端到端延迟。加载、输入预构造及公开句预热不在上述 forward 总时长内。
两轮样本数与长度不同，不能据此推导生产 SLA；但这次运行没有显示提速。

本次完整语境比旧 quote 更长，还保留了原导出中的 `confluence-local-id` 注释。
例如误放行的 exporter 输入从 93 token 增为 271，health 输入从 100 增为 188。
这提示后续应评估结构边界与非事实导出标记的处理，不能一味扩大上下文。
本轮记录结果后未改变构造策略重测，也不据已见错误调整后继续称未见验证。

## 权限与范围

运行使用真实 PermissionService。每次涉及私有原文的 forward 前及结果释放前，
重新检查当前本地/native 来源权限和冻结源文件 SHA、文档身份、原文位置，无正授权缓存。
模型与分词器本地加载；没有调用远程裁判、生成模型、检索、embedding/Milvus 或浏览器。

显式 ACL 负例 Local Setup 在带标记的数据库副本上验证拒绝，finally 恢复，
原数据库未修改。原权重 SHA 与源文件 hash 已核实，未使用 mock 模型、权限或输入。
核验基于明确提供的冻结导出正文，不宣称重新导出了 Confluence 最新正文。

本次是实际分类器质量测试，**不是新问题的检索—生成—绑定—核验端到端验收**，
也没有启用 Thinking 旁路或修改 Fast 调用次数。未重新运行单元测试并冒充分类质量结果；
上一轮程序测试的 1043 passed 仍只属于上一轮代码验证记录。

## 外部证据

目录：`D:/AI-QA-Assistant/claim-verification-20261019/actual-minicheck-compare/`。

- `protocol.json`、`frozen-inputs.json`：推断前冻结的输入、策略及代码/数据/权重身份。
- `original_excerpt.predictions.jsonl`、`structured_context.predictions.jsonl`：逐条结果与未核验原因。
- 两轮 `*.summary.json`、`comparison-summary.json`：全计划、实际分类与共同样本分别汇总。
- `loading-info.json`、`acl-negative.json`：实际权重加载和 ACL 副本检查。
- `results-manifest.json`：最终证据文件 SHA。

外部脚本为上一层目录的 `run_actual_verification.py`，日志为 `actual-minicheck-compare.log`。
私有原文、预测明细、数据库与权重均未加入仓库，历史文件未覆盖。
