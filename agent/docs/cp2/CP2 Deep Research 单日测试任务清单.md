# CP2 Deep Research 测试与优化双人分工计划

## 1. 计划目标

本轮工作以测试和效果验证为主，不默认 Deep Research 或更复杂的流程一定更好。通过固定基线、分层评估和三组对照实验，明确：

- Deep Research 是否比普通 Fast Chat 更完整、可靠；
- Page Index 分层检索是否改善跨章节、多文档问题；
- 当前主要问题出在 Plan、Retrieval、Evidence、Report、Citation 还是 Runtime；
- 来源链接和分层检索两项 P0 修复是否产生真实收益。

Planner 全面改成 ReAct 不属于本轮范围。先测清现有 Planner、Worker 和检索工具，再决定后续优化方向。

---

## 2. 成员 A：效果基线与评估体系

### 2.1 建立固定基线

负责冻结并记录：

- 模型及模型版本；
- temperature、top_p、max_tokens 等生成参数；
- Planner、Worker 和报告 Prompt 版本；
- Search top_k、Chunk、Embedding、rerank、fallback 等检索配置；
- Git Commit 和运行环境；
- 测试文档版本、content_hash 和 SourceManifest；
- 每道题允许访问和禁止访问的文档范围。

同一道题的三组实验必须使用相同问题文本、相同文档版本和相同权限范围。Provider 失败或 fallback 必须记录，不能静默替换模型后混入同一组结果。

### 2.2 建立 15～20 题测试集

第一版目标为 18 题，覆盖：

- 多文档信息汇总；
- 跨章节关联；
- 新旧版本冲突；
- 信息不足、应拒绝下结论；
- 数字比较与条件判断；
- 表格或图表信息；
- 引用定位和原文打开；
- 无关文档干扰；
- 权限范围限制。

问题不能全部是容易直接命中的普通事实题。每题至少定义：

```text
case_id
category
question
source_manifest
expected_behavior
required_facts
forbidden_claims
key_source_locations
```

其中 `expected_behavior` 可为 `answer`、`degraded`、`refuse`、`request_more_information` 或 `conflict_review`。

不要求成员 A 人工逐条编写和核对完整金标准。初始 Required Facts、关键原文和预期行为可从冻结文档自动生成，后续由 Codex 基于原文统一复核。

### 2.3 建立分层评估规则

负责定义统一的评估数据结构和评分规则：

| 层级 | 重点指标 |
| --- | --- |
| Plan | 问题覆盖率、重复任务率、依赖合理性、任务可执行性 |
| Retrieval | 正确文档命中率、Evidence Recall@K、MRR、噪声比例、越权命中 |
| Evidence | 是否读取正确原文、证据充分性、Locator 完整性、冲突识别 |
| Report | 正确性、完整性、Faithfulness、Answer Relevance、限制披露 |
| Citation | 引用支持率、引用覆盖率、链接可打开率、原文定位正确性 |
| Runtime | 延时、工具调用数、Token、retry、fallback、恢复次数 |

评估采用“确定性自动检查 + 基于冻结原文的模型评审 + Codex 最终复核异常案例”，成员无需人工逐项核对全部报告。

### 2.4 成员 A 交付物

- 冻结实验配置；
- 15～20 题测试集；
- 每题 SourceManifest 和文档版本记录；
- 六层评估 Schema；
- 自动评分规则和模型评分 Prompt；
- 三组实验统一结果表模板；
- 失败类型定义。

---

## 3. 成员 B：实验执行、指标采集与 P0 修复

### 3.1 建立可重复实验链路

负责为每次运行保存：

```text
run_id
group
case_id
environment
request
plan
retrieval_hits
observations
verified_evidence
claims
report
citations
events
runtime_metrics
error
```

每题每组至少运行 3 次。失败运行必须保留，不能只保留成功样本。

Runtime 至少采集总延时及各阶段延时、Search / Read / 总工具调用数、Token、retry、fallback、Checkpoint 恢复次数、terminal status、failure_stage 和 error_code。

### 3.2 完成三组对照实验

| 组别 | 说明 |
| --- | --- |
| G1：Fast Chat | 普通快速问答链路 |
| G2：Current Deep Research | 当前 Planner、Worker 和当前 Search 实现 |
| G3：Deep Research + Page Index | 保持 Research 流程不变，仅启用 Page Index / 层级导航检索 |

正式运行规模：

```text
15～20 题 × 3 组 × 每题至少 3 次
```

三组实验除入口与待比较的检索能力外，模型、问题、文档版本、权限范围和主要生成参数保持一致。

最终需要回答：

- G2 相比 G1 是否提高 Correctness、Completeness、Faithfulness 和 Citation Quality；
- G2 增加了多少延时、Token 和工具调用；
- G3 相比 G2 是否提高多文档、跨章节题的正确文档命中率和 Evidence Recall@K；
- G3 是否引入更多噪声、fallback 或延时；
- 复杂流程是否出现更慢但效果不升反降的情况。

### 3.3 P0：修复来源链接

检查并修复完整链路：

```text
Document.source_url
→ Chunk.source_url
→ Search Hit
→ Observation
→ Verified Evidence
→ Citation
→ Research API
→ 前端引用标签
→ 打开原文
```

要求：

- 文档存在 source_url 时必须完整传递到 Citation；
- URL 对应实际 Evidence 来源，不能由前端猜测生成；
- Confluence 来源能打开原始页面；
- 本地来源使用系统支持的原文查看接口或定位方式；
- 没有可用 URL 时不渲染假链接；
- 链接打开测试可以自动执行；
- 原文链接打不开数量为 0。

### 3.4 P0：接入 Page Index 分层检索

将 Deep Research 的 Search 工具适配到 toolset 已有 Page Index / 层级导航能力：

```text
Research Task
→ Search Tool Adapter
→ Page Index / Hierarchical Navigation
→ Page / Section Candidate
→ Original Range Read
→ Observation
→ Verified Evidence
```

要求：

- 不重写 toolset 的 Page Index 核心实现；
- 不绕过 SourceManifest 和权限检查；
- Page Index 命中不能直接成为 Verified Evidence；
- 必须继续读取原文并生成 Locator；
- Page Index 不可用时明确记录 fallback；
- G2 与 G3 必须能够独立切换和复现；
- 不把本地词法 fallback 记录为 Page Index 命中；
- 优先评估跨章节、多文档、表格和干扰文档问题。

### 3.5 成员 B 交付物

- 可重复的批量实验入口；
- 三组全部原始运行结果；
- Runtime 和检索指标；
- 来源链接 P0 修复及测试；
- Page Index Search Adapter 及测试；
- 自动硬门槛检查结果；
- 可用于现场演示的真实在线环境。

---

## 4. Codex 负责的复核工作

在两位成员完成运行后，由 Codex 统一完成：

- 从冻结原文生成或校正 Required Facts；
- 核对关键 Evidence 是否来自正确原文；
- 判断 Evidence 是否足以支持 Claim；
- 识别“版本不同但不构成语义冲突”的误判；
- 核对信息不足题是否应该拒绝或降级；
- 核对 Citation 是否支持对应断言；
- 抽查所有异常评分和临界分数；
- 汇总三组结果并形成最终效果结论。

以下确定性项目直接由程序检查，模型评分不得覆盖：

- 是否使用 Manifest 外证据；
- URL 是否真实存在并能打开；
- Citation 是否缺失；
- Claim 是否完全没有 Evidence；
- 原文版本、Hash 和 Locator 是否匹配。

---

## 5. 硬门槛

| 指标 | 门槛 |
| --- | ---: |
| 越权 Evidence | 0 |
| 断裂 Citation | 0 |
| 无 Evidence 的事实结论 | 0 |
| 原文链接打不开 | 0 |
| 事实 Claim 引用覆盖率 | 100% |
| Faithfulness 平均分 | ≥ 4 / 5 |
| Answer Relevance 平均分 | ≥ 4 / 5 |

判断规则：

- 任一安全或引用硬门槛未通过，不能宣布当前版本可正式交付；
- `completed` 只代表流程结束，不代表效果合格；
- `degraded` 如果正确披露资料不足，可以是正确结果；
- Page Index 只有在质量提高且硬门槛不退化时才保留；
- Deep Research 如果不优于 Fast Chat，应如实记录问题类型和性能代价。

---

## 6. 失败分类

失败必须记录最早出现问题的层级：

```text
PLAN_COVERAGE
PLAN_DUPLICATION
PLAN_DEPENDENCY
RETRIEVAL_DOCUMENT_MISS
RETRIEVAL_SECTION_MISS
RETRIEVAL_NOISE
RETRIEVAL_PERMISSION_LEAK
EVIDENCE_ORIGINAL_NOT_READ
EVIDENCE_INSUFFICIENT
EVIDENCE_WRONG_LOCATOR
EVIDENCE_CONFLICT_MISCLASSIFIED
REPORT_INCORRECT
REPORT_INCOMPLETE
REPORT_UNFAITHFUL
CITATION_MISSING
CITATION_UNSUPPORTED
CITATION_BROKEN_LINK
RUNTIME_TIMEOUT
RUNTIME_PROVIDER_FAILURE
RUNTIME_FALLBACK
RUNTIME_RECOVERY_FAILURE
```

例如，正确文档没有检索到并导致报告缺失，应记录 `root_cause = RETRIEVAL_DOCUMENT_MISS`、`downstream_effect = REPORT_INCOMPLETE`，不能只记录“最终报告不好”。

---

## 7. 最终共同交付

- 固定的 15～20 题 Deep Research 评测集；
- 每题三组、每组至少 3 次的完整运行记录；
- Plan、Retrieval、Evidence、Report、Citation、Runtime 六层结果；
- Fast Chat、Current Deep Research、Deep Research + Page Index 对照表；
- 来源链接 P0 修复结果；
- Page Index P0 接入及效果结论；
- 主要失败案例和根因分布；
- 是否达到硬门槛的结论；
- 下一轮优化优先级；
- 一套可重复运行并可用于现场演示的真实测试环境。

