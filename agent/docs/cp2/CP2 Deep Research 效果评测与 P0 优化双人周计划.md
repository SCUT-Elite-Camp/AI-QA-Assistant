# CP2 Deep Research 效果评测与 P0 优化双人周计划

> 周期：2026-09-14 ～ 2026-09-18  
> 定位：效果评测周，不以新增流程节点或扩大功能范围为主要目标  
> 协作方式：Day 1 冻结协议，Day 2～Day 4 独立工作，Day 5 唯一正式集成与现场验收

---

## 1. 本周目标

本周不默认“Deep Research 比普通问答更好”，而是通过可复现的分层评测回答以下问题：

1. 当前 Deep Research 相比普通 Fast Chat，是否在复杂问题上更完整、更可靠、更可追溯；
2. 当前性能损失是否换来了真实质量收益；
3. Page Index / 层级导航接入后，是否改善跨章节、多文档问题；
4. 失败主要发生在 Plan、Retrieval、Evidence、Report、Citation 还是 Runtime；
5. 来源链接与分层检索两项 P0 是否确实解决了主要失败，而不是只增加复杂度。

本周完整闭环：

```text
冻结实验环境
→ 建立真实问题集与标准答案
→ 运行 Fast Chat / 当前 Deep Research 基线
→ 分层定位失败原因
→ 隔离实现两项 P0
→ 运行 Deep Research + Page Index 对照组
→ Day 5 集成
→ 回归与现场演示
→ 输出可复现结论和下一轮优化清单
```

---

## 2. 本周范围

### 2.1 P0 必须完成

- 冻结模型、参数、文档版本、SourceManifest 和检索配置；
- 建立 15～20 个真实复杂问题的评测集，目标为 18 题；
- 每个实验条件每题至少运行 3 次；
- 完成 Plan、Retrieval、Evidence、Report、Citation、Runtime 六层评估；
- 对比普通 Fast Chat、当前 Deep Research、Deep Research + Page Index 三组；
- 修复或完成可验证方案：来源链接必须稳定可打开；
- 完成 Deep Research Search 与 Page Index / 层级导航能力的适配验证；
- 输出失败案例集、逐层指标、三组对照结果和优化结论；
- Day 5 完成唯一一次正式集成、完整回归和现场演示。

### 2.2 P1 有余力再做

- 自动生成 HTML 可视化评测报告；
- 增加 Judge 模型辅助评分，但不得替代人工复核；
- 增加更多权限隔离与服务重启案例；
- 对同一问题做不同 K 值、Chunk Size 或温度消融；
- 建立可重复执行的 Nightly Evaluation。

### 2.3 本周明确不做

- Planner 全面改写为 ReAct；
- 新增 Web Research；
- 多 Agent 或并行 Worker；
- 自动 Replan；
- 修改普通问答的产品交互；
- 仅凭个别 Demo Case 宣布效果提升；
- 在基线冻结后同时修改模型、Prompt、索引和检索参数；
- 为了提高分数放宽权限边界或引用校验规则。

---

## 3. 双人职责

## 成员 A：Evaluation & Quality Owner

成员 A 负责回答：

> 什么问题算难、什么结果算正确，以及提升是否真实成立。

主要任务：

- 设计 18 题真实评测集；
- 为每题建立问题类型、资料范围、关键事实和不可回答边界；
- 编写 Gold Evidence、Expected Claims 和期望引用位置；
- 定义六层评分 Rubric；
- 审核 Plan 是否覆盖问题、是否重复、依赖是否合理；
- 人工复核 Evidence、Report、Citation；
- 建立冲突、信息不足、权限边界等高风险 Case；
- 对三组结果进行盲评或去系统标识评审；
- 维护失败分类表和根因判断；
- 给出是否达到发布门槛的最终质量意见。

成员 A 不负责：

- 修改 Deep Research Runtime；
- 修改 toolset 检索实现；
- 为了适配实现结果临时改 Gold Answer；
- 只根据语言流畅度给报告高分。

## 成员 B：Experiment, Runtime & P0 Integration Owner

成员 B 负责回答：

> 实验能否稳定复现、每层数据能否采集，以及两项 P0 是否真正改善结果。

主要任务：

- 冻结并记录模型、Prompt、参数、代码版本和文档版本；
- 建立批量运行和结果归档目录；
- 采集 Research Job、Plan、Task、Search Hit、Evidence、Claim、Citation 和 Runtime 数据；
- 运行普通 Fast Chat 与当前 Deep Research 基线；
- 统计正确文档命中率、Evidence Recall@K、噪声比例和运行成本；
- 修复来源 URL 在采集、持久化、报告到前端打开链路中的断点；
- 在不随意重写检索层的前提下，为 Deep Research Search 增加 Page Index 能力适配；
- 运行 Deep Research + Page Index 对照组；
- 完成自动硬门槛检查、回归测试和复现脚本；
- Day 5 负责正式集成、服务启动和演示环境。

成员 B 不负责：

- 单方面修改评分标准；
- 在基线跑完前优化 Prompt 或检索参数；
- 用本地词法 fallback 冒充 Page Index 结果；
- 修改 SourceManifest 权限边界；
- 因某组运行失败而静默删掉样本。

## 共同负责

- Day 1 评测协议冻结；
- 每日失败 Case Review；
- Day 4 P0 修复验收；
- Day 5 正式集成与三组回归；
- 现场演示脚本和最终结论；
- 明确区分“指标提升”“无显著变化”和“结果退化”。

---

## 4. Day 1 必须冻结的实验协议

### 4.1 代码与环境

记录以下字段，整个基线阶段不得变化：

```text
git_commit
git_branch
python_version
node_version
os
milvus_version
embedding_model
llm_model
prompt_version
planner_config
retrieval_config
document_manifest_hash
evaluation_dataset_version
```

模型统一为：

```text
qwen3.7-flash-2026-07-15
```

如模型不可用，必须将该次运行记为 Provider Failure，不得静默切换模型后混入同一组结果。

### 4.2 生成参数

至少固定并记录：

- temperature；
- top_p；
- max_tokens；
- timeout；
- retry 次数；
- 最大工具调用数；
-最大 Graph 跳转次数；
- Search top_k；
- Chunk Size / Overlap；
- Embedding 模型与维度；
- 是否启用 rerank；
- 是否启用 keyword fallback；
- 报告语言；
- 引用生成规则。

若当前代码没有显式暴露某参数，记录为 `implementation_default`，并定位实际默认值所在文件。

### 4.3 文档与权限范围

基线语料以已导入的 Confluence 工程记录目录树为主：

```text
Root Page: 34045953
Root + Descendants: 80 pages
Space: RAG
```

为每道题保存独立 SourceManifest，至少包含：

```text
doc_id
page_id
version
last_updated
content_hash
source_url
permission_scope
```

同一题三次运行必须使用相同 `manifest_hash`。新旧版本冲突题使用专门冻结的冲突 Fixture，不得直接依赖会持续变化的线上页面。

### 4.4 三组实验条件

| 组别 | 入口 | 检索方式 | Research 流程 | 目的 |
| --- | --- | --- | --- | --- |
| G1 | Fast Chat | 当前普通问答检索 | 否 | 判断复杂流程是否有收益 |
| G2 | Deep Research | 当前 Deep Research Search | 是 | 建立现状基线 |
| G3 | Deep Research | Page Index / 层级导航 | 是 | 判断分层检索是否有效 |

除检索方式和产品入口允许的必要差异外，模型、文档版本、问题文本和核心生成参数保持一致。

### 4.5 运行规模

正式目标：

```text
18 questions × 3 groups × 3 runs = 162 runs
```

执行分两层：

```text
Smoke：6 questions × 3 groups × 1 run = 18 runs
Full：18 questions × 3 groups × 3 runs = 162 runs
```

Smoke 不替代 Full，只用于尽早发现配置、链接或采集故障。

---

## 5. 评测问题集设计

### 5.1 题型配额

| 类型 | 数量 | 最低难度要求 |
| --- | ---: | --- |
| 多文档信息汇总 | 3 | 至少依赖 3 份文档 |
| 跨章节关联 | 2 | 答案必须组合不同章节事实 |
| 新旧版本冲突 | 2 | 必须说明冲突命题和版本依据 |
| 信息不足 / 应拒绝下结论 | 2 | 资料中明确缺少决定性证据 |
| 数字比较与条件判断 | 2 | 至少包含一次计算或条件分支 |
| 表格或图表信息 | 2 | 关键答案来自表格、矩阵或图示 |
| 引用定位和原文打开 | 2 | 每个关键断言必须可打开原文 |
| 无关文档干扰 | 1 | SourceManifest 中加入高相似噪声文档 |
| 权限范围限制 | 2 | 存在相关但 Manifest 外的文档 |
| 合计 | 18 | 不允许全部退化成单点事实题 |

### 5.2 建议的 18 个问题方向

以下是题目方向，Day 1 由成员 A 根据真实文档补齐精确措辞和 Gold Evidence：

1. 汇总 Agent 模块从 W23 到 W34 的主要能力演进，并按阶段说明证据；
2. 对比 W32 与 W34 Agent 交付，指出新增、保留和未完成项；
3. 汇总 M1、M3、M4 在某一共同 Sprint 的跨模块依赖；
4. 将系统架构演进记录与对应周报交叉验证；
5. 从模块生命周期归档与 Master Report 中定位同一能力的上下游关系；
6. 判断两个版本对同一接口或状态定义是否真正冲突；
7. 面对更新时间不同但适用范围不同的说明，决定是否应标记冲突；
8. 仅凭现有工程记录能否确认某项性能提升百分比；
9. 现有资料能否证明某项功能已在生产环境完成验收；
10. 比较两个 Sprint 的交付数量、完成条件或覆盖模块；
11. 根据明确条件判断某周是否达到既定 Gate；
12. 从 Cross-Module Delivery Matrix 提取指定模块关系；
13. 从表格中比较不同模块在同一阶段的状态；
14. 为包含 3 个以上关键断言的回答逐项提供可打开引用；
15. 点击引用后核对原文段落、页面版本和更新时间；
16. 在加入标题相似但内容无关文档后，回答指定模块的真实交付；
17. 当相关页面不在 SourceManifest 时，系统是否明确拒绝使用；
18. 当用户请求跨越其授权范围汇总时，系统是否只回答允许范围并披露限制。

### 5.3 每题标准数据结构

```yaml
case_id: DR-EVAL-001
category: multi_document_summary
question: "..."
difficulty: hard
source_manifest_id: "..."
allowed_doc_ids: []
forbidden_doc_ids: []
gold_documents: []
gold_evidence:
  - doc_id: "..."
    locator: "..."
    expected_fact: "..."
expected_claims: []
must_not_claim: []
expected_behavior: answer | degraded | refuse | ask_for_clarification
scoring_notes: "..."
```

---

## 6. 六层评估指标

## 6.1 Plan

重点检查：

- 问题覆盖率；
- 重复任务率；
- 任务依赖有效率；
- Task 是否可执行；
- Acceptance Criteria 是否可验证；
- 是否出现与问题无关的固定模板任务。

评分建议：

```text
Plan Coverage = 被任务覆盖的必需子问题数 / 必需子问题总数
Duplicate Task Rate = 重复或高度重合任务数 / 总任务数
Dependency Validity = 合理依赖边数 / 总依赖边数
```

## 6.2 Retrieval

重点检查：

- Correct Document Hit Rate；
- Evidence Recall@K；
- MRR；
- 噪声比例；
- Manifest 外命中次数；
- Page Index 是否先定位正确页面/章节再读取正文。

计算规则：

```text
Document Hit Rate@K = Top-K 中命中 Gold Document 的题数 / 总题数
Evidence Recall@K = Top-K 中命中的 Gold Evidence 数 / Gold Evidence 总数
Noise Ratio@K = Top-K 中无关结果数 / K
Unauthorized Hit Count = Manifest 外结果数量
```

## 6.3 Evidence

重点检查：

- 是否读取了正确原文，而不只是 Search Snippet；
- Evidence 是否满足结论；
- Locator、版本、Hash 是否完整；
- 是否存在断章取义；
- 冲突题是否保留双方完整证据；
- 信息不足题是否正确识别 Evidence Gap。

评分为 1～5 分，同时记录：

```text
Evidence Sufficiency
Evidence Correctness
Original Read Success Rate
Locator Completeness
```

## 6.4 Report

重点检查：

- Correctness；
- Completeness；
- Faithfulness；
- Answer Relevance；
- 冲突和限制披露；
- 是否出现无证据的新事实。

所有维度采用 1～5 分。Faithfulness 以 Evidence 为准，不以“写得像真的”作为评分依据。

## 6.5 Citation

重点检查：

- Citation 是否支持对应 Claim；
- 每个事实 Claim 是否有引用；
- Source URL 是否存在；
- 点击后能否打开；
- 是否定位到正确页面和足够完整的原文；
- 页面版本和时间是否与 Evidence 一致。

计算规则：

```text
Citation Coverage = 有有效引用的事实 Claim 数 / 事实 Claim 总数
Citation Support Rate = 真正支持对应 Claim 的引用数 / 引用总数
Broken Link Rate = 无法打开的引用数 / 引用总数
```

## 6.6 Runtime

每次运行记录：

```text
total_latency_ms
planning_latency_ms
retrieval_latency_ms
verification_latency_ms
report_latency_ms
tool_call_count
search_call_count
read_call_count
input_tokens
output_tokens
estimated_cost
retry_count
fallback_count
checkpoint_resume_count
terminal_status
failure_stage
error_code
```

除平均值外必须报告 P50、P95、最大值和三次运行方差。

---

## 7. 发布硬门槛

以下指标任何一项不满足，均不得宣布通过：

| 硬门槛 | 要求 |
| --- | ---: |
| 越权 Evidence | 0 |
| 断裂引用 | 0 |
| 无证据事实结论 | 0 |
| 原文链接打不开 | 0 |
| 事实 Claim 引用覆盖率 | 100% |
| Faithfulness 平均分 | ≥ 4.0 / 5 |
| Answer Relevance 平均分 | ≥ 4.0 / 5 |

附加判定原则：

- G3 只有在质量提高且硬门槛不退化时，才认为 Page Index 接入有效；
- 若 G3 质量提升但 Runtime 成本显著增加，必须明确披露收益与代价；
- 若 Deep Research 不优于 Fast Chat，不掩盖结果，直接记录失败类型；
- `completed` 不等于质量通过，最终仍以分层指标为准；
- `degraded` 若正确披露资料不足，可以是正确行为。

---

## 8. 两项 P0 的技术边界与验收

## P0-1：来源链接修复

目标链路：

```text
Confluence / Local Source
→ Document.source_url
→ Chunk.source_url
→ Search Hit
→ Observation
→ Verified Evidence
→ Citation
→ Research API
→ Web Citation Tag
→ 打开对应原文
```

成员 B 负责逐层定位 source_url 丢失点，成员 A 使用 Citation Case 验收。

验收要求：

- 评测集所有 Citation 均具有非空 URL 或项目支持的可解析本地定位符；
- Source URL 与实际 Evidence 文档一致；
- 点击引用可以打开，不返回 404；
- 不使用前端猜测路径补造 URL；
- 无 URL 的证据不能被渲染为假链接；
- Broken Link Rate = 0；
- 原文位置、版本和时间可核对。

## P0-2：Page Index / 分层检索适配

目标链路：

```text
Research Task
→ Search Tool Adapter
→ Page Index / Hierarchical Navigation
→ Page / Section Candidate
→ Original Range Read
→ Observation
→ Verified Evidence
```

边界：

- 不重写 toolset 的 Page Index 核心实现；
- 不绕过 SourceManifest 与权限校验；
- 不允许检索命中直接成为 Verified Evidence；
- Page Index 不可用时必须显式记录 fallback；
- G2 与 G3 分开运行，不能把新策略结果混入旧基线；
- Planner 本周不全面改为 ReAct。

验收要求：

- 跨章节和多文档子集的 Evidence Recall@K 高于或不低于 G2；
- Noise Ratio@K 不得明显恶化；
- Unauthorized Hit Count = 0；
- Search → Original Read → Evidence 边界保持成立；
- fallback 次数可观测；
- 至少 6 个 Page Index 重点 Case 完成三次重复运行。

---

## 9. 五天双人安排

| 日期 | 成员 A：Evaluation & Quality | 成员 B：Experiment, Runtime & P0 | 集成规则 |
| --- | --- | --- | --- |
| Day 1 | 题集、Gold Evidence、评分 Rubric、盲评表 | 环境冻结、运行清单、采集 Schema、复现脚本骨架 | 只冻结协议与数据格式 |
| Day 2 | 完成 18 题标注；审核 G1/G2 样本 | 运行 G1/G2 Smoke 与 Full；采集完整轨迹 | 不修改基线实现 |
| Day 3 | 六层评分、失败分类、P0 验收 Case | 分析指标；隔离完成来源链接与 Page Index 适配 | 不接双方未完成改动 |
| Day 4 | 盲评 G3；比较 G1/G2/G3；给出质量结论 | 运行 G3 Full；自动硬门槛；P0 回归 | 各自独立收口 |
| Day 5 | 现场验收、抽样复核、演示讲解 | 唯一正式集成、全量回归、启动演示环境 | 唯一正式集成日 |

---

## 10. 每日详细任务与门禁

## Day 1：Baseline Freeze

### 成员 A

1. 从 80 页 Confluence 工程记录中选取 18 个复杂真实问题；
2. 确保九类问题达到配额；
3. 为每题标注 Gold Document、Gold Evidence、Expected Claim；
4. 标注必须拒答、必须降级和必须披露冲突的题；
5. 完成六层 Rubric；
6. 建立人工评分表；
7. 定义 Reviewer 不一致时的仲裁规则；
8. 冻结数据集版本 `dr_eval.v1`。

### 成员 B

1. 记录 Git Commit、分支和运行环境；
2. 固定 `qwen3.7-flash-2026-07-15`；
3. 固定生成参数、检索参数和最大动作数；
4. 导出 80 页文档版本与 Hash；
5. 为每题生成冻结 SourceManifest；
6. 建立 Run ID 与目录结构；
7. 定义运行记录 JSON Schema；
8. 准备 Fast Chat、Deep Research 两种运行入口；
9. 验证事件、Plan、Evidence、Report、Citation 可被采集；
10. 完成 2 题预检，不计入正式结果。

### Day 1 Gate

- 18 题全部具备可执行标注；
- 模型、参数、文档和代码版本全部冻结；
- 同一题可证明使用相同 manifest_hash；
- 运行产物 Schema 可同时支持 G1/G2/G3；
- Day 2 开始后不得根据模型回答反向修改 Gold。

## Day 2：Current Baseline

### 成员 A

1. 复核 Gold Evidence 原文位置；
2. 验证权限 Case 的 allowed / forbidden 文档；
3. 对 G1/G2 输出隐藏系统标识；
4. 开始 Plan、Evidence、Report、Citation 人工评分；
5. 标记机械计划、重复任务、误判冲突和无依据结论；
6. 记录有争议样本，不即时修改规则。

### 成员 B

1. 先运行 6 题 G1/G2 Smoke；
2. 验证 source_url、事件和 Token 数据未丢失；
3. 运行 18 题 G1，每题 3 次；
4. 运行 18 题 G2，每题 3 次；
5. 保存原始请求、响应、日志和中间实体；
6. 汇总 Runtime 指标；
7. 计算 Retrieval 初步指标；
8. 将失败保留在数据集中，不静默重跑覆盖；
9. Provider Failure 可追加补跑，但原失败记录必须保留。

### Day 2 Gate

- G1 54 次、G2 54 次均有记录；
- 每次运行都有唯一 Run ID；
- G2 可追踪 Plan → Evidence → Claim → Citation；
- 失败率、fallback 和 retry 可计算；
- 基线阶段没有代码或参数漂移。

## Day 3：Failure Analysis & Isolated P0

### 成员 A

1. 完成 G1/G2 六层评分；
2. 按最早失败层分类，而不是只记“报告错误”；
3. 输出 Top 10 失败 Case；
4. 区分检索没找到、找到了没读、读到了没使用、引用错位；
5. 建立来源链接专项验收集；
6. 建立 Page Index 重点 6 题；
7. 给出两项 P0 的预期提升指标。

### 成员 B

1. 计算 G1/G2 分层指标；
2. 对 source_url 做全链路审计；
3. 隔离修复来源链接，不改变报告事实生成逻辑；
4. 为 Deep Research Search 设计 Page Index Adapter；
5. 保留 Manifest 和 Tool Contract；
6. 增加 Page Index 开关或实验组配置；
7. 记录 Page Index 命中、层级路径和 fallback；
8. 使用 6 个重点 Case 做单次开发验证；
9. 不将开发验证结果计入正式 G3。

### Day 3 Gate

- 每个主要失败可归属到明确层级；
- 来源链接专项 Case 本地全部可打开；
- Page Index Adapter 不越过 SourceManifest；
- Search Hit 仍不能直接成为 Evidence；
- G2 基线原始结果不可被覆盖。

## Day 4：Controlled Experiment

### 成员 A

1. 对 G3 结果做去标识评分；
2. 完成 G1/G2/G3 横向比较；
3. 检查硬门槛；
4. 对跨章节、多文档子集单独分析；
5. 对信息不足和权限题单独分析；
6. 判断质量提升是否足以抵消延时和调用成本；
7. 输出保留、回退或继续实验的建议。

### 成员 B

1. 冻结 P0 实验版本；
2. 运行 G3 Smoke；
3. 运行 G3 18 题 × 3 次；
4. 计算 Retrieval、Runtime 和稳定性指标；
5. 自动检查越权 Evidence、无证据 Claim、断裂 Citation；
6. 对所有 Citation 执行打开测试；
7. 完成来源链接回归；
8. 完成 Page Index Adapter 单元与集成测试；
9. 准备 Day 5 可合并提交和回滚点。

### Day 4 Gate

- G3 54 次正式运行全部归档；
- 三组共 162 次运行可追溯；
- 硬门槛检查结果可复现；
- A 的人工评分与 B 的自动指标可关联到同一 Run ID；
- Day 4 结束后停止新增能力。

## Day 5：唯一正式集成与现场演示

### 集成顺序

```text
1. 合并来源链接修复
2. 运行 Citation 回归
3. 合并 Page Index Adapter
4. 运行 Search / Manifest / Evidence 边界测试
5. 运行 6 题 Smoke 对照
6. 运行硬门槛检查
7. 回归普通 Fast Chat
8. 回归当前 Deep Research
9. 回归 Deep Research + Page Index
10. 启动现场演示环境
```

### 成员 A

- 抽查三类关键题：多文档、冲突/不足、权限；
- 现场核验引用打开与原文一致性；
- 讲解评分标准、基线和对照结果；
- 明确哪些结论通过、哪些仍有风险；
- 签署质量 Gate。

### 成员 B

- 完成唯一正式代码集成；
- 运行测试、启动后端、前端、Milvus；
- 准备固定 SourceManifest 与演示问题；
- 展示 Research Plan、审批、执行状态和最终报告；
- 展示 Citation 标签、打开原文和权限限制；
- 展示三组指标对照与失败案例；
- 提供一键复现命令和回滚方案。

### Day 5 Gate

- 普通 Chat 未被 Deep Research 改动破坏；
- 来源链接 100% 可打开；
- Page Index 关闭时 G2 行为仍可复现；
- Page Index 开启时层级路径和 fallback 可观测；
- 越权证据、断裂引用和无证据事实结论均为 0；
- 完成现场演示全流程。

---

## 11. 失败分类规范

每个失败只记录一个“最早根因层”，并可增加后续影响：

```text
P_PLAN_COVERAGE
P_PLAN_DUPLICATION
P_PLAN_DEPENDENCY
R_DOC_MISS
R_SECTION_MISS
R_NOISE
R_PERMISSION_LEAK
E_ORIGINAL_NOT_READ
E_INSUFFICIENT
E_WRONG_LOCATOR
E_CONFLICT_MISCLASSIFIED
REP_INCORRECT
REP_INCOMPLETE
REP_UNFAITHFUL
CIT_MISSING
CIT_UNSUPPORTED
CIT_BROKEN_LINK
RUN_TIMEOUT
RUN_PROVIDER_FAILURE
RUN_FALLBACK
RUN_RECOVERY_FAILURE
```

示例：正确文档未检索到，最终报告缺失结论，应记录：

```text
root_cause = R_DOC_MISS
downstream_effect = REP_INCOMPLETE
```

不能只记录 `REPORT_BAD`。

---

## 12. 实验产物结构

建议产物目录：

```text
eval/deep_research/
├── datasets/
│   └── dr_eval_v1.yaml
├── manifests/
│   └── DR-EVAL-001.json
├── configs/
│   ├── frozen_common.json
│   ├── fast_chat.json
│   ├── deep_research_current.json
│   └── deep_research_page_index.json
├── runs/
│   ├── G1/
│   ├── G2/
│   └── G3/
├── annotations/
│   ├── rubric.md
│   └── human_scores.csv
├── analysis/
│   ├── layered_metrics.csv
│   ├── failure_cases.md
│   └── ablation_summary.md
└── reports/
    └── deep_research_eval_report.md
```

每次 Run 至少保存：

```text
request.json
environment.json
plan.json
retrieval.json
evidence.json
claims.json
report.md
citations.json
runtime.json
events.json
score.json
```

---

## 13. 三组结果表

最终报告至少包含：

| 指标 | G1 Fast Chat | G2 Current DR | G3 DR + Page Index | G3 vs G2 |
| --- | ---: | ---: | ---: | ---: |
| Document Hit Rate@K |  |  |  |  |
| Evidence Recall@K |  |  |  |  |
| Noise Ratio@K |  |  |  |  |
| Evidence Sufficiency |  |  |  |  |
| Correctness |  |  |  |  |
| Completeness |  |  |  |  |
| Faithfulness |  |  |  |  |
| Answer Relevance |  |  |  |  |
| Citation Coverage |  |  |  |  |
| Broken Link Rate |  |  |  |  |
| P50 Latency |  |  |  |  |
| P95 Latency |  |  |  |  |
| Tool Calls |  |  |  |  |
| Token Usage |  |  |  |  |
| Fallback Count |  |  |  |  |

必须同时给出全量结果与以下子集结果：

- 多文档 + 跨章节；
- 冲突 + 信息不足；
- 表格 / 图表；
- 权限 + 干扰；
- Citation 专项。

---

## 14. 现场演示设计

现场只选 3 题，但必须覆盖不同风险：

### Demo 1：多文档 / 跨章节

展示：

```text
用户选择 Deep Research
→ 指定 SourceManifest
→ 生成非模板化 Plan
→ 用户审批
→ Page Index 定位页面与章节
→ 原文读取
→ 完整报告与引用
```

### Demo 2：信息不足或真实冲突

展示：

```text
系统识别缺口或具体冲突命题
→ 不强行给确定结论
→ 展示双方完整原文或缺失条件
→ 用户通过对话确认处理方式
→ 报告保留决定与限制
```

如果当前“冲突裁决后恢复”仍未达到正式能力，应明确标记为未完成，不用按钮或前端文案伪装。

### Demo 3：权限与引用

展示：

```text
存在相关但 Manifest 外文档
→ Search 不返回越权证据
→ 报告只使用授权资料
→ 点击 Citation 打开正确 Confluence 原文
```

演示前准备：

- 固定演示账号和权限；
- 固定 3 个问题文本；
- 固定 SourceManifest；
- 预热模型与 Milvus；
- 检查 Confluence 登录状态；
- 保留录屏或静态结果作为网络异常备份；
- 不使用 Mock 结果冒充在线结果。

---

## 15. 本周 Definition of Done

只有同时满足以下条件，本周才算完成：

### 基线

- 18 题评测集完成；
- 每题有 Gold Evidence 和预期行为；
- G1/G2/G3 每题至少 3 次；
- 162 次运行全部可追踪；
- 模型、参数、版本和 Manifest 可复现。

### 分层评估

- 六层指标均有结果；
- 每个失败有最早根因层；
- 不以单一总分掩盖权限或 Citation 风险；
- 至少输出 Top 10 失败案例。

### P0

- 来源链接从文档到前端全链路可验证；
- Broken Link Rate = 0；
- Page Index 组可独立开关和复现；
- Page Index 不绕过 SourceManifest；
- Search Hit 仍需 Original Read 才能成为 Evidence。

### 质量门槛

- 越权 Evidence = 0；
- 断裂引用 = 0；
- 无证据事实结论 = 0；
- Citation Coverage = 100%；
- Faithfulness ≥ 4/5；
- Answer Relevance ≥ 4/5。

### 集成与演示

- Day 1～Day 4 无中间正式集成；
- Day 5 完成唯一正式集成；
- 普通 Chat 回归通过；
- 3 个现场 Demo Case 可在线执行；
- 最终报告明确回答 Deep Research 与 Page Index 是否带来净收益。

---

## 16. 最终交付物

成员 A：

- `dr_eval_v1` 真实问题集；
- Gold Evidence 与 Expected Claims；
- 六层评分 Rubric；
- 人工评分结果；
- 失败案例和质量结论；
- 现场演示讲解稿。

成员 B：

- 冻结配置和环境清单；
- 三组批量运行及全量原始结果；
- 分层指标统计；
- 来源链接 P0 修复与测试；
- Page Index Adapter 与实验开关；
- 自动硬门槛检查；
- 一键复现与现场启动说明。

共同交付：

- 《Deep Research 三组对照评测报告》；
- 《Deep Research 失败案例与根因清单》；
- 《P0 修复前后效果对比》；
- 《下一轮优化优先级建议》；
- 可在线运行的现场演示。

---

## 17. 本周最终原则

```text
先冻结，再测试；
先分层定位，再修改；
先证明问题，再做 P0；
只在 Day 5 正式集成；
不因流程更复杂就默认效果更好；
不以漂亮报告替代正确证据；
不以 completed 替代质量验收。
```

本周最终应能够用数据回答：

> Deep Research 在哪些复杂问题上优于 Fast Chat，代价是多少；Page Index 在哪些场景产生了可重复的增益；剩余失败究竟属于哪一层。
