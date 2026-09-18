# CP2 Deep Research 全量测试、结果分析与修复报告

> 报告日期：2026-09-15  
> 评测范围：Fast Chat（G1）与当前 Deep Research（G2）  
> 数据集：`cp2-deep-research-cases.v1`，18 个用例，每组每题运行 3 次  
> Page Index（G3）：未纳入本轮验收，因为当前代码库没有工具/数据层提供的 Page Index Provider

## 1. 报告结论

本轮完成了 18 个冻结问题、G1/G2 两个实验组、每题 3 次的 108 次基线运行，并对全部运行生成了六层评分记录。原始执行中，Fast Chat 成功 6 次、失败 48 次；Deep Research 成功 46 次、失败 8 次。完成 Judge 补评分后，108 条记录均进入最终评分集，无坐标缺失和批次结构错误。

最终硬门槛结果为：

| 实验组 | 运行数 | 原始执行成功 | 硬门槛通过 | 结论 |
| --- | ---: | ---: | ---: | --- |
| G1 Fast Chat | 54 | 6 | 0 | 不满足 Deep Research 质量门槛 |
| G2 Current Deep Research | 54 | 46 | 13 | 明显优于 G1，但尚不满足正式质量门槛 |

G2 相较 G1 在正确性、完整性、忠实度和答案相关性上均有提升，但平均分仍低于 4/5 的目标。当前最明确的问题集中在计划覆盖、报告完整性、答案相关性和忠实度；历史结果中的 Retrieval/Evidence 指标由于运行时尚未输出内部 Trace，只能视为暂定结论，不能据此直接认定检索层实现失败。

本轮同时完成了评测可观测性、来源链路、Judge 兼容性、模型配置、报告生成和超时诊断数据保留等修复。新版本已经能够从持久化 Job 读取 Observation、Evidence、Finding、Claim 和 Verification，后续定向复测可得到真实的六层数据。

## 2. 评测目标与范围

本轮评测用于回答两个问题：

1. 当前 Deep Research 是否比普通 Fast Chat 更完整、可靠；
2. 当前失败主要发生在 Plan、Retrieval、Evidence、Report、Citation 还是 Runtime。

本轮不回答“Page Index 是否提升效果”。Page Index 属于工具层/数据层能力，当前仓库没有注册 `page_index`、`search_page_index` 或 `navigate_page_index` Provider。评测框架保留 G3 定义，但不会用本地词法检索冒充 Page Index，也不会把 G3 缺失计为 B 侧交付失败。

## 3. 冻结评测配置

### 3.1 数据与代码基线

- 仓库：`SCUT-Elite-Camp/AI-QA-Assistant`
- 分支：`agent-dev`
- 冻结提交：`74f2d44e3eaf67739c87bb888db940051b30991b`
- 数据来源：Confluence `RAG` 空间的本地冻结快照
- 用例数：18
- 重复次数：每题每组 3 次
- SourceManifest：逐题冻结允许文档、禁止文档、版本、内容哈希、来源 URL 和权限范围

### 3.2 生成与检索配置

- 当前冻结模型：`doubao-seed-2-1-turbo-260628`
- API：火山引擎 OpenAI-compatible API
- Temperature：`0.1`
- Max tokens：`2000`
- Timeout：`60s`
- Retrieval mode：`hybrid`
- Top K：`5`
- Embedding：`BAAI/bge-small-en-v1.5`
- Rerank：关闭
- 权限限制：SourceManifest 的 `document_ids` 作为硬 allowlist

注意：108 次候选答案生成主要来自此前的 `qwen3.8-flash` 运行；其中 70 条无有效报告的记录由确定性规则保留，38 条包含报告但缺失 Judge 的记录后来使用当前 Doubao 配置补评分。因此该目录是“完整评分结果”，不是单一 Doubao 生成模型的纯净对照基线。后续做模型横向比较时必须重新冻结并分目录运行，不能混合聚合。

## 4. 评测集覆盖

### 4.1 评测集是什么

本轮使用的是冻结评测集 `cp2-deep-research-cases.v1`，而不是测试时临时提出问题。每个 Case 都是一个可重复执行的测试契约，至少包含：

| 字段 | 作用 |
| --- | --- |
| `case_id` | 用例稳定编号，例如 `DR-A-001` |
| `question` | 三组实验必须使用的同一问题原文 |
| `expected_behavior` | 预期应回答、降级、拒绝、补充信息或进入冲突复核 |
| `allowed_document_ids` | 当前用例唯一允许访问的文档集合 |
| `forbidden_document_ids` | 明确禁止访问的文档，用于检测越权 |
| `required_facts` | 回答必须覆盖的事实及其稳定 `fact_id` |
| `forbidden_claims` | 报告中不得出现的错误结论 |
| `key_source_locations` | 金标准文档、Chunk、章节和短引用，用于计算检索命中 |
| `source_manifest` | 绑定文档版本、哈希、URL 与权限范围的冻结清单 |

金标准不依赖测试结束后人工凭印象评分：题目、必要事实、禁止结论和关键来源位置都已预先固化。人工或 Codex 复核只用于调查失败原因，不直接篡改机器评分。

### 4.2 覆盖场景

18 个真实问题覆盖以下类型：

- 多文档汇总与生命周期比较；
- 跨章节关联；
- 新旧版本冲突与版本范围歧义；
- 信息不足，应拒绝下结论；
- 数字比较与条件判断；
- 表格信息理解；
- 引用定位和原文打开；
- 无关文档干扰；
- 权限范围与越权隔离；
- 当前状态综合判断。

用例不仅包含容易命中的直接问答，还包含冲突、干扰、信息不足、权限和跨文档推理场景。

### 4.3 单次运行记录

每个 Case 在每个实验组重复 3 次。每次运行生成独立 `run_id`，并记录同一份问题哈希、Manifest 哈希、允许/禁止文档、模型配置哈希和文档版本。单次 Run Record 包含 Plan、Retrieval Hit、Observation、Verified Evidence、Claim、Report、Citation、Event 与 Runtime Metrics，失败运行同样保留。

批量聚合前会检查 18 × 2 × 3 = 108 个坐标是否完整，并检查同一 Case 在不同组和不同重复之间是否发生问题、权限、Manifest、模型配置或 Prompt 漂移。坐标缺失、重复或关键配置漂移都会产生 `batch_errors`，该批次不能作为有效对照。

## 5. 六层评估标准

| 层级 | 评估内容 |
| --- | --- |
| Plan | 问题覆盖、任务重复、依赖合法性、任务可执行性 |
| Retrieval | 正确文档命中、Evidence Recall@K、MRR、噪声、权限泄漏 |
| Evidence | 是否读取原文、事实覆盖、Locator 有效性、冲突识别 |
| Report | 正确性、完整性、Faithfulness、相关性、限制披露、冲突处理 |
| Citation | 引用支持率、断言覆盖率、链接可打开率、Locator 匹配率 |
| Runtime | 总耗时、工具调用、Token、重试、fallback、恢复和 Provider 失败 |

硬门槛：越权证据、断裂引用、无证据断言、打不开的来源链接均为 0；事实引用覆盖率为 100%；Faithfulness 和 Answer Relevance 均不低于 4/5。

### 5.1 一条结果是怎样产生的

```text
冻结 Case + SourceManifest
        │
        ├── G1：调用 Fast Chat
        └── G2：创建 Research Job → 生成/批准 Plan → 执行任务 → 生成 Report
                                      │
                                      ▼
                    保存原始 Run Envelope（成功与失败都保留）
                                      │
                                      ▼
              转换成六层 Run Record，并执行 Schema / Invariant 校验
                         │                         │
                         │                         └── 确定性检查
                         └── 冻结证据 + 候选报告 → Model Judge（1–5 分）
                                                   │
                                                   ▼
                         硬门槛判定 → Failure Code → Root Cause → 批量聚合
```

评分不是让模型直接给一个“总分”。Manifest、权限、哈希、Locator、引用存在性和链接状态由代码确定性计算；只有语义质量交给 Model Judge。最终结果以硬门槛是否全部通过为准，平均分只用于比较趋势。

### 5.2 Plan 层计算

| 指标 | 计算方式 |
| --- | --- |
| Question Coverage | `计划覆盖的 required fact 数 / required fact 总数` |
| Duplicate Task Rate | `重复规范化 Query 数 / Task 总数` |
| Dependency Valid | 对 Task 依赖图做环检测，无环才为真 |
| Task Executable Rate | 同时具有 `task_id` 和非空 Query 的 Task 数 / Task 总数 |

计划中的 `covers` 由 Task 问题、目的和验收条件与冻结 `required_facts` 匹配得到。Coverage 小于 100% 记为 `PLAN_COVERAGE`；出现重复记为 `PLAN_DUPLICATION`；循环或非法依赖记为 `PLAN_DEPENDENCY`。

### 5.3 Retrieval 层计算

| 指标 | 计算方式 |
| --- | --- |
| Correct Document Recall | `命中的关键文档数 / 金标准关键文档数` |
| Evidence Recall@K | `Top-K 命中的关键 Chunk 数 / 金标准关键 Chunk 数` |
| MRR | 第一个关键文档命中排名的倒数；无命中为 0 |
| Noise Ratio | `非关键文档 Hit 数 / 全部 Hit 数` |
| Permission Leak Count | Hit 中不属于 allowlist 的文档数 |

正确文档未全部命中记为 `RETRIEVAL_DOCUMENT_MISS`；文档命中但关键 Chunk 未全部命中记为 `RETRIEVAL_SECTION_MISS`；噪声比例大于 0.5 记为 `RETRIEVAL_NOISE`；任何越权 Hit 直接触发权限硬门槛。

### 5.4 Evidence 层计算

| 指标 | 计算方式 |
| --- | --- |
| Original Read Rate | 通过 `read_document_range` 或本地原文读取产生的 Evidence 数 / Evidence 总数 |
| Required Fact Coverage | Evidence 支持的 required fact 数 / required fact 总数 |
| Locator Valid Rate | 文档版本、内容哈希和 Locator 均与冻结 Manifest 一致的 Evidence 数 / Evidence 总数 |
| Conflict Identified | 冲突题是否出现 `conflict` 或 `version_evolution` 标记 |

搜索摘要只是 Observation，不能直接作为 Verified Evidence。必须读取冻结原文，且版本、哈希、Locator 可校验，才能进入证据层。事实覆盖不足、未读原文、定位错误和冲突误判分别映射到对应 Evidence Failure Code。

### 5.5 Report 的确定性检查与 Model Judge

报告层由两部分共同评分：

1. **确定性检查**：用冻结用例中的 `match_any` 检查必要事实是否出现在报告；检查 `forbidden_claims` 是否被错误输出；检查报告行为是否与 `expected_behavior` 一致。
2. **Model Judge**：Judge 只能看到问题、预期行为、必要事实描述、冻结原文 Evidence、Claim 及候选报告，不允许使用外部知识，也不能修改确定性结果。

Judge 对以下六个维度分别给出 1–5 的整数分：

| Judge 维度 | 5 分含义 | 低分典型原因 |
| --- | --- | --- |
| Correctness | 结论与冻结原文一致，数字推理正确 | 事实错误、数值或版本判断错误 |
| Completeness | 覆盖全部问题和 required facts | 漏项、只回答部分比较维度 |
| Faithfulness | 每项事实均由引用的已核验证据支持 | 引入证据外推断或引用不支持断言 |
| Answer Relevance | 直接回答问题且没有无关展开 | 答非所问、重复流程描述 |
| Limitation Disclosure | 缺失信息、权限边界和降级原因披露完整 | 信息不足时仍强行下结论 |
| Conflict Handling | 正确区分冲突与版本演进，并使用日期和权威性 | 把普通版本变化误判为冲突 |

Judge 必须同时返回其认为已支持的 `required_fact_ids_supported`、`unsupported_claim_ids` 和简短理由。Judge 不能覆盖权限、哈希、Locator、引用存在性或链接检查。若 Judge 给出低 Faithfulness 却遗漏 unsupported claim IDs，Parser 会保守加入待复核标记，避免错误通过。

### 5.6 Citation 层计算

| 指标 | 计算方式 |
| --- | --- |
| Citation Support Rate | 标记为确实支持 Claim 的 Citation 数 / Citation 总数 |
| Factual Claim Citation Coverage | 有 Citation 的事实 Claim 数 / 全部事实 Claim 数 |
| Link Open Rate | 实际检查成功的必需来源 URL 数 / 必需来源 URL 总数 |
| Locator Match Rate | Citation Locator 与所引用 Evidence Locator 一致的数量 / Citation 总数 |
| Unsupported Claim Count | 无 Evidence、Evidence ID 无效或 Judge 判为不支持的事实 Claim 数 |

引用缺失、不支持结论、来源链接打不开、越权来源都会单独记录，不能被报告文字质量分抵消。

### 5.7 Runtime 层记录

Runtime 不用单一分数掩盖异常，而是保存总延时、各阶段延时、Search/Read/总工具调用数、输入输出 Token、重试、Fallback、Checkpoint 恢复、Provider Failure、终态、失败阶段和错误码。超时、Provider 失败、Fallback 与恢复失败分别映射为 Runtime Failure Code。

### 5.8 硬门槛如何判定

单次运行只有同时满足以下条件才记为 `hard_gate_pass = true`：

| 硬门槛 | 通过条件 |
| --- | --- |
| Permission Leak Count | `= 0` |
| Broken Citation Count | `= 0` |
| Unsupported Factual Claim Count | `= 0` |
| Unopenable Source Link Count | `= 0` |
| Factual Claim Citation Coverage | `>= 1.0`，即 100% |
| Faithfulness | `>= 4/5` |
| Answer Relevance | `>= 4/5` |
| Invariant Errors | 为空 |

因此“Job completed”不等于“评测通过”。任意一项硬门槛不通过，该次运行即失败。

### 5.9 根因和批量均值如何计算

每次运行可以产生多个 Failure Code。系统按照 `Plan → Retrieval → Evidence → Report → Citation → Runtime` 的预定义顺序选择第一个 Failure Code 作为 `root_cause`，其余作为 `downstream_effects`。这是稳定的工程归因规则，不代表后续层的问题不需要修复。

批量报告按实验组分别计算：

- `hard_gate_pass_count`：该组通过全部硬门槛的运行数；
- 各 Judge 维度均值：该组所有具有数值评分的运行之算术平均值；
- Evidence Recall、Latency、Tool Calls：同样按有效数值做算术平均；
- 不删除失败运行，不用成功运行替换失败运行；
- 缺少模型分数时不按 0 随意填充，而是先保留缺失并进入补评分流程。

### 5.10 如何阅读本报告中的分数

- 1–5 分是 Judge 对语义维度的分项评价，不是系统总分；
- 0–1 比率由代码根据冻结金标准计算；
- 硬门槛是最终验收条件；
- G1/G2 均值用于观察相对趋势，不能掩盖越权、断链或无证据结论；
- 本轮旧记录缺少内部 Retrieval Trace，因此旧 `Evidence Recall@K = 0` 不具备最终诊断效力；该限制已经在结果部分单独披露。

## 6. 执行过程

### 6.1 108 次基线运行

- G1：18 题 × 3 次，共 54 次；成功 6 次，失败 48 次；平均耗时约 82.7 秒。
- G2：18 题 × 3 次，共 54 次；成功 46 次，失败 8 次；平均耗时约 147.4 秒。
- G1/G2 合计：108 次，运行坐标完整。

### 6.2 Judge 评分恢复

第一次 Judge 阶段有 38 条失败。根因不是答案本身，而是评分进程被错误代理 `127.0.0.1:9` 阻断，无法访问模型 Provider。

处理过程包括：

1. 保留全部失败记录，没有删除或伪造分数；
2. 多次验证 Qwen、DeepSeek、Kimi 和 Doubao 的模型名称、权限、额度及返回结构；
3. 将最终评分模型切换到可用的 Doubao 配置；
4. 禁用该模型不需要的 Thinking 输出；
5. 扩展 Judge Parser，使其兼容嵌套评分结构、展示型字段名和缺失列表字段；
6. 仅重跑失败的 38 条 Judge，不重复执行全部 108 次候选答案生成；
7. 将 38 条有效评分合并回总目录，得到 108 条完整评分记录。

### 6.3 最终评分完整性

- `record_count`：108
- `expected_record_count`：108
- `missing_coordinates`：0
- `batch_errors`：0
- 全部记录均经过确定性硬门槛计算

## 7. 量化结果

| 指标 | G1 Fast Chat | G2 Deep Research | G2 相对表现 |
| --- | ---: | ---: | --- |
| Correctness | 1.22 | 2.39 | 提升 |
| Completeness | 1.17 | 2.06 | 提升 |
| Faithfulness | 1.22 | 2.74 | 提升 |
| Answer Relevance | 1.24 | 2.04 | 提升 |
| 硬门槛通过 | 0/54 | 13/54 | 提升，但仍不达标 |
| 平均耗时 | 82.7s | 147.4s | G2 更慢 |
| 平均工具调用 | 0 | 5.67 | G2 执行了研究工具链 |

`evidence_recall_at_k` 在历史聚合中为 0。该数值不能解释为真实检索 Recall 为 0，因为旧评测转换器只能从最终 Citation 反推 Retrieval Hit，缺少原始 Observation、chunk 和 score。此问题已修复，新运行需要通过定向复测重新计算。

## 8. 失败分析

### 8.1 G1

G1 的 54 次运行全部未通过硬门槛。主要表现为：

- Answer Relevance 未通过：52 次；
- Faithfulness 未通过：51 次；
- 无法形成足够 Evidence 和完整 Report；
- 4 次断裂或不支持结论的 Citation；
- 2 次事实断言引用覆盖不足。

这说明普通 Fast Chat 不适合作为复杂多文档研究任务的可靠完成路径。

### 8.2 G2

G2 有 13/54 次通过硬门槛。历史评分中的主要失败计数为：

- `PLAN_COVERAGE`：46 次；
- `REPORT_INCOMPLETE`：46 次；
- `REPORT_INCORRECT`：38 次；
- `REPORT_UNFAITHFUL`：37 次；
- Answer Relevance 硬门槛失败：41 次；
- Faithfulness 硬门槛失败：35 次；
- Unsupported factual claim：15 次。

Retrieval/Evidence 相关代码在旧结果中出现较多，但由于旧运行缺失内部 Trace，其根因排序只能暂定。后续应优先复测 Plan Coverage、Report 完整性和硬门槛失败用例，再根据新 Observation/Evidence 数据确认是否真的需要修改检索策略。

## 9. 已完成的修复

### 9.1 数据接入与来源链路

- 拉取并保存 Confluence RAG 空间文档快照；
- SourceManifest 补充文档版本、哈希、URL 和权限范围；
- 来源 URL 缺失时支持本地原文路由；
- 修复前端来源入口和引用卡片的打开行为；
- 原文读取仍严格受当前 Job 的冻结 Manifest 限制。

### 9.2 计划、证据与报告质量

- Planner 从生硬固定模板改为模型生成并保留确定性回退；
- Worker 从命中单行扩展为带上下文的原文区间读取；
- Search Observation 与 Verified Evidence 分离持久化；
- 报告生成失败时使用已核验证据回退，不输出无依据内容；
- 改进冲突识别，避免仅因标题、日期或描述范围不同就判定语义冲突；
- 最终报告保留引用、原文、版本、限制和冲突处理信息。

### 9.3 模型与 Judge 兼容性

- 支持统一配置模型、API Base、Temperature、Timeout 和 Thinking Mode；
- HTTP 错误保留受限长度的 Provider 响应信息，便于诊断且不暴露 API Key；
- Judge Parser 兼容 Kimi 嵌套格式和 Doubao 展示型字段名；
- Faithfulness 低于满分但未返回 unsupported claim IDs 时，保守生成待复核标记，避免错误放行。

### 9.4 六层评测可观测性

- 新增只读接口：`GET /api/research/jobs/{research_id}/evaluation-trace`；
- 接口返回持久化 Observation、Verified Evidence、Finding、Claim 和 Verification；
- Observation 新增检索 score；
- 转换器优先使用真实 Trace 构造 Retrieval/Evidence/Claim 层，不再仅依赖最终引用；
- 支持 `--case-ids` 定向运行指定冻结用例；
- 超时运行仍保留 `research_id`、Job 状态、事件和已有 Trace；
- 新增确定性失败归因与硬门槛报告生成器。

## 10. 修复验证

针对本轮新增和修改的链路执行了以下验证：

- Worker Observation/Evidence 分离与 score 持久化；
- Research Control Plane API；
- Benchmark case scope 与运行汇总；
- Judge Parser 多 Provider 返回格式；
- Failure Analysis 聚合；
- Evaluation Trace API。

最终针对性测试结果：`20 passed`，`git diff --check` 通过。

在线持久化 Job 验证结果：

- Job 最终状态：`completed`；
- Observation：6；
- Verified Evidence：6；
- Finding：3；
- Claim：3；
- Verification：6；
- Observation 中可读取 `tool_name`、`doc_id`、`locator_hint` 和 `score`。

另一次 `DR-A-001 / G2 / 1 次` 定向运行超过 600 秒评测期限，报告模型阶段发生连接中止。该次运行按 Runtime 超时保留，不计为通过。任务后来在持久化运行时完成，说明还存在“模型调用阻塞导致评测等待超时”的性能与超时边界问题。

## 11. 当前仍未完成或不能宣称完成的事项

1. **G2 尚未达到质量门槛**：当前只有 13/54 次通过硬门槛。
2. **新 Trace 下的定向复测尚未形成完整新评分批次**：旧 Retrieval/Evidence 结论仍需复核。
3. **Runtime 延迟仍高**：G2 平均约 147 秒，个别任务超过 600 秒。
4. **Token 指标仍不可用**：公共 API 返回未完整暴露各阶段 Token 用量。
5. **Page Index 未实现**：应由工具/数据层提供 Provider 后，B 侧再做 Worker 适配和 G3 对照实验。
6. **不能把混合模型结果作为纯模型对比**：本轮生成与补评分存在不同模型阶段，后续纯模型对照必须重新冻结。

## 12. 下一轮建议

1. 使用新 Trace 对 G2 的硬门槛失败用例做定向复测，不重跑已确认无关的全部任务；
2. 优先修复 Plan Coverage、Report Completeness、Faithfulness 和 Answer Relevance；
3. 对每个失败用例输出 Observation → Evidence → Claim → Citation 的完整链路，确认根因后再决定是否修改检索层；
4. 将模型调用设置为可中断的阶段级超时，避免 Job 已完成但 Benchmark 先超时；
5. 工具/数据层交付 Page Index 后，再建立独立 G3 基线；
6. 模型横向实验按 Provider/Model 独立目录运行，禁止混合聚合。

## 13. 交付产物

面向评审和汇报只保留两个主要入口：

| 主要交付 | 内容 | 路径 |
| --- | --- | --- |
| 完整说明报告 | 评测集、方法、量化规则、结果、失败分析、修复、验证、限制与下一步 | `agent/docs/cp2/CP2 Deep Research 全量测试、结果分析与修复报告.md` |
| 评测数据与结果工作簿 | 总览图表、108 条运行明细、18 个用例、失败分布与产物索引 | `agent/docs/cp2/CP2 Deep Research 评测数据与结果.xlsx` |

JSON、JSONL、CSV、SourceManifest、Schema 和生成脚本仍保留在 `eval/deep_research_a` 与 `eval/reports/qwen38-full-g1-g2-0915` 下，作为机器复算和审计证据。日常评审不需要逐个打开；具体路径已经集中列在 Excel 的 `Artifact index` 工作表中。

## 14. 最终验收判断

本轮“建立基线、完成 G1/G2 对照、分层评分、保留失败、分析根因、补齐评测可观测性和范围内 P0 修复”的工作已完成。

当前 Deep Research 可以证明比 Fast Chat 更适合复杂研究任务，但尚不能宣称达到正式质量门槛。最准确的交付状态是：**评测基础设施和第一版完整基线已交付，主要缺陷已定位并完成可观测性修复；效果优化仍需基于新 Trace 做定向迭代。**
