# CP2 Deep Research 全量测试、结果分析与修复报告

> 报告日期：2026-09-22
>
> 有效基线：G1 Fast Chat 正式批次、G2 Current Deep Research 正式批次
>
> 数据集：`cp2-deep-research-cases.v1`，18 题，每组每题运行 3 次
>
> 结果口径：正式批次中的瞬时故障坐标由同配置定点重试结果替换
>
> Page Index（G3）：本轮不测试，等待工具层/数据层提供正式 Provider

## 1. 执行摘要

本报告已废弃此前混合模型、混合配置、异常运行和后补评分组成的旧基线，改为只使用本次重新执行的 G1 与 G2 正式批次。两组都使用同一份冻结的 18 题评测集，每题运行 3 次，共 108 个有效坐标。

| 实验组 | 正式坐标 | 首轮成功 | 定点重试后有效成功 | 有效失败 | 完成率 |
| --- | ---: | ---: | ---: | ---: | ---: |
| G1 Fast Chat | 54 | 42 | 46 | 8 | 85.2% |
| G2 Current Deep Research | 54 | 51 | 54 | 0 | 100% |

核心结论：

1. G2 已跑通 18×3 的完整链路，定点重试后 54/54 坐标均有有效结果。
2. G1 定点排除网络关闭、读取超时和外层超时后，仍有 8 次稳定失败，全部为 `no_relevant_context`。
3. G2 首轮的 3 次失败中，两次是 HTTP 502，一次是报告边界字段过长；字段长度问题已修复并通过回归测试，三个坐标重试均成功。
4. 当前数据能够支持“运行完成率、失败类型、耗时和链路稳定性”结论；新批次尚未重新执行六层 Judge 评分，因此不能沿用旧报告的 Faithfulness、Answer Relevance、硬门槛通过率等数值。
5. G1 与 G2 实际使用的模型不完全相同，本轮可以比较系统链路完成情况，但不能把差异全部归因于 Fast Chat 与 Deep Research 架构本身。

## 2. 评测目标

本轮评测回答以下问题：

- 普通 Fast Chat 与当前 Deep Research 能否在同一冻结数据集上完成稳定执行；
- 失败发生在检索、回答生成、研究执行、报告渲染还是外部模型服务；
- Deep Research 的计划、检索、证据、报告、引用和运行时数据是否具备分层评分条件；
- 当前实现中有哪些可复现缺陷，修复后是否能够通过定点复测。

本轮暂不回答“Page Index 是否提升效果”。仓库当前没有可用的正式 Page Index Provider，不能用本地词法或普通混合检索冒充 Page Index 组。

## 3. 评测集说明

### 3.1 冻结数据集

- 数据集 ID：`cp2-deep-research-cases.v1`
- 语言：`zh-CN`
- 用例数：18
- 数据来源：Confluence `RAG` 空间的冻结快照
- 每题均绑定 SourceManifest
- 每个实验组每题运行 3 次

每个 Case 至少包含：

| 字段 | 用途 |
| --- | --- |
| `case_id` | 稳定用例编号 |
| `question` | 三组实验共用的问题原文 |
| `expected_behavior` | 应回答、降级、拒绝或提示信息不足 |
| `allowed_document_ids` | 允许访问的文档硬范围 |
| `forbidden_document_ids` | 越权检查所需的禁止文档 |
| `required_facts` | 回答必须覆盖的事实 |
| `forbidden_claims` | 回答不得出现的结论 |
| `key_source_locations` | 正确文档、Chunk、章节和短引用 |
| `source_manifest` | 文档版本、哈希、URL 与权限范围 |

### 3.2 场景覆盖

18 题覆盖：多文档信息汇总、跨章节关联、新旧版本冲突、信息不足时拒绝下结论、数字比较与条件判断、表格信息解析、引用定位和原文打开、无关文档干扰、权限范围限制，以及当前状态与历史会议记录综合。

## 4. 实验组与配置

### 4.1 G1：Fast Chat

- 运行目录：`outputs/deep_research_benchmark/g1-a95b-formal-18x3-0922`
- 实际服务模型：`qwen3.8-2.4t-a95b`
- Thinking：启用；该模型在当前服务配置下要求开启 Thinking
- 检索模式：`hybrid`
- Top K：`5`
- 最低分数：`0`
- Embedding：`BAAI/bge-small-en-v1.5`
- Milvus：已启动并用于混合检索

定点重试目录：

- `g1-a95b-transient-retry-0922-dr005`
- `g1-a95b-transient-retry-0922-final`
- `g1-a95b-transient-retry-0922-last`

### 4.2 G2：Current Deep Research

- 运行目录：`outputs/deep_research_benchmark/g2-formal-18x3-0921`
- 实际服务模型：`qwen3.8-27b`
- 检索模式：`hybrid`
- Top K：`5`
- 最低分数：`0`
- Embedding：`BAAI/bge-small-en-v1.5`
- Research Graph：计划、审批、任务执行、覆盖检查、报告生成、完成状态

定点重试目录：`g2-formal-failed-retry-0922`。

### 4.3 配置可比性说明

两组使用相同数据集、问题、SourceManifest、检索模式、Top K 和 Embedding，但实际生成模型不同。因此可以比较端到端完成率、稳定失败类型和链路可恢复性，但不应直接宣称 G2 的回答质量优势完全来自 Deep Research 架构。严格架构对照仍需在同一模型、同一参数、同一服务窗口下重跑 G1/G2。

此外，两个运行目录内的 `frozen_environment.json` 仍错误记录为 `qwen3.7-flash-2026-07-15`。该字段与实际服务模型不一致，属于评测元数据捕获缺陷。本报告以运行时实际配置和执行记录为准，后续需要修复配置快照的模型读取逻辑。

## 5. 评测方法

### 5.1 六层评价框架

| 层级 | 评价内容 | 主要数据 |
| --- | --- | --- |
| Plan | 是否覆盖问题、任务是否重复、依赖是否合理 | Research Plan、Task、Dependency |
| Retrieval | 正确文档命中率、Evidence Recall@K、噪声比例 | Observation、命中文档、检索排名 |
| Evidence | 是否读取正确原文、证据是否充分 | Evidence、Chunk、相邻上下文 |
| Report | 正确性、完整性、Faithfulness、相关性 | Claim、Finding、最终报告 |
| Citation | 引用是否支持断言、来源链接能否打开 | Citation、Source URL、Source Route |
| Runtime | 延时、动作数、工具调用数、Fallback 次数 | Job Event、Trace、统计字段 |

### 5.2 硬门槛

正式质量验收硬门槛：越权证据 0、断裂引用 0、无证据结论 0、原文链接打不开 0、引用覆盖率 100%、Faithfulness 平均不低于 4/5、Answer Relevance 平均不低于 4/5。

本次报告只公布由新批次重新产生的运行数据。当前两批尚未完成新的六层 Judge 批量评分，因此上述质量硬门槛暂不判定，不复用旧批次评分。

### 5.3 有效结果替换规则

正式批次遇到 HTTP 502、远端连接关闭、Read Timeout、测试执行器外层 Timeout，或已经修复且有回归测试覆盖的确定性代码异常时，只重跑失败坐标，不重跑全部 108 次。重试成功结果替换同一 `case_id + run_index + group` 的瞬时失败；稳定业务失败如 `no_relevant_context` 保留为有效失败，不通过无限重试掩盖。

## 6. Deep Research 被测流程

```text
用户问题 + SourceManifest
        |
        v
创建 Research Job，立即返回 research_id
        |
        v
Planner 生成研究计划
        |
        v
用户审批或修改计划
        |
        v
Research Graph 按依赖执行任务
        |
        +--> Search / Read 工具检索授权知识库
        |        |
        |        v
        |   Observation -> Evidence
        |        |
        |        v
        |   Finding / Claim / Citation
        |
        v
Coverage / Verification 检查
        |
        +--> 信息不足：降级、说明限制或等待处理
        |
        v
Renderer 生成研究报告
        |
        v
保存事件、Checkpoint、状态与最终报告
        |
        v
前端对话展示报告，右侧展示执行状态
```

## 7. G1 正式结果

### 7.1 数量与完成率

| 指标 | 结果 |
| --- | ---: |
| 正式坐标 | 54 |
| 首轮成功 | 42 |
| 首轮失败 | 12 |
| 瞬时故障经定点重试恢复 | 4 |
| 最终有效成功 | 46 |
| 最终有效失败 | 8 |
| 有效完成率 | 85.2% |
| 有效平均耗时 | 123.2 秒 |
| 有效耗时中位数 | 81.5 秒 |

平均耗时受 `DR-A-018 r2` 约 34 分钟的异常等待显著拉高，因此中位数比平均数更能代表常规体验。

### 7.2 首轮瞬时故障

- `DR-A-005` 三次：远端连接关闭或读取超时；
- `DR-A-006 r2`：外层执行超时。

定点重试后，这四个坐标均获得成功结果，因此不计入最终业务失败。

### 7.3 稳定业务失败

最终 8 次失败全部为 `fast_chat_terminal_status:no_relevant_context`：

| 用例 | 失败次数 | 场景 | 观察 |
| --- | ---: | --- | --- |
| `DR-A-012` | 3/3 | 表格状态核对 | Fast Chat 未稳定检索到 Goals 表中的目标行 |
| `DR-A-015` | 2/3 | 权限范围限制 | 同题三次结果不稳定，仅 1 次得到可用上下文 |
| `DR-A-018` | 3/3 | 多文档当前状态综合 | 未能同时取得 Goals 与会议纪要所需上下文 |

这些失败集中在结构化表格、严格权限过滤和多文档综合，说明 Fast Chat 的单轮检索在复杂资料定位上仍存在稳定性缺口。

## 8. G2 正式结果

### 8.1 数量与完成率

| 指标 | 结果 |
| --- | ---: |
| 正式坐标 | 54 |
| 首轮成功 | 51 |
| 首轮失败 | 3 |
| 定点重试恢复 | 3 |
| 最终有效成功 | 54 |
| 最终有效失败 | 0 |
| 有效完成率 | 100% |
| 平均耗时 | 107.0 秒 |
| 耗时中位数 | 6.9 秒 |
| 平均动作数 | 7.63 |
| 平均工具调用数 | 7.63 |
| 平均证据数 | 4.39 |

有效报告状态中包含 51 个 `complete` 和 3 个 `degraded`。`degraded` 是系统在证据不足或边界条件下给出的受控结果，不等于执行失败。

### 8.2 首轮失败与处理

| 坐标 | 首轮失败 | 处理 | 重试结果 |
| --- | --- | --- | --- |
| `DR-A-001 r3` | HTTP 502 | 同配置定点重试 | 成功 |
| `DR-A-002 r2` | HTTP 502 | 同配置定点重试 | 成功 |
| `DR-A-008 r2` | `ResearchLimitation.message` 超过 2000 字触发 ValidationError | 修复 Renderer 边界并回归测试 | 成功 |

### 8.3 G2 缺陷根因

`DR-A-008 r2` 已完成主要研究执行，但报告渲染阶段把过长的 limitation 文本写入受长度约束的数据模型，导致最终报告失败。该问题属于输出边界处理缺陷，不是检索失败。

修复内容：

- 在 `deep_research/renderer.py` 对 limitation message 使用统一的 `_bounded_text(..., max_length=2000)`；
- 增加报告边界回归测试；
- 对原失败 Job 重新执行报告渲染，状态恢复为 `complete`；
- 复核生成 Markdown 长度为 11109，单条 limitation 最大长度为 2000；
- 定点重跑 `DR-A-008` 后成功。

## 9. G1 与 G2 对照

| 维度 | G1 Fast Chat | G2 Deep Research | 当前结论 |
| --- | --- | --- | --- |
| 有效完成率 | 85.2% | 100% | G2 链路完成率更高 |
| 稳定业务失败 | 8 次 `no_relevant_context` | 0 | G2 对复杂检索场景覆盖更稳定 |
| 瞬时服务故障 | 有 | 有 | 两组均受外部模型服务影响 |
| 结构化流程 | 单轮检索回答 | 计划、执行、验证、报告 | G2 可记录更多分层过程数据 |
| 受控降级 | 能力有限 | 3 个 degraded 报告 | G2 能保留边界与限制说明 |
| 严格质量分 | 未重算 | 未重算 | 暂不做质量优劣定论 |

当前最可靠的结论是：G2 在这 18 题上的端到端可完成性优于 G1。但由于实际模型不同、六层 Judge 评分尚未重算，不能把 100% 完成率解释为 100% 回答正确，也不能将差异完全归因于系统架构。

## 10. 本轮完成的修复

### 10.1 检索与证据

- 增加相邻 Chunk 读取，避免证据只包含命中单行或局部碎片；
- 对相邻 Chunk 的重叠内容进行去重；
- 保留 SourceManifest 的文档允许范围，防止越权扩展；
- 来源打开链路支持本地 Source Route；
- 基准检查能够识别来源链接与终态失败。

### 10.2 Planner、Worker 与验证

- 修复计划任务校验和资料范围冲突；
- Worker 的 finding statement 增加 4000 字边界；
- Verifier 的数字识别正则避免把字母数字 ID 误判为数值结论；
- 保留失败 Job 的 Observation、Evidence、Finding、Claim 与 Verification，便于定位六层问题。

### 10.3 报告生成

- 修复 `ResearchLimitation.message` 超过 2000 字导致的报告渲染失败；
- 对历史失败 Job 验证可重新渲染完整报告；
- 为边界截断增加回归测试。

### 10.4 运行环境与产物管理

- 启动并验证 Milvus，支持 Hybrid Retrieval；
- 补齐 `rank-bm25` 运行依赖；
- 按正式批次、重试批次和归档结果整理 `outputs/deep_research_benchmark`；
- 增加输出目录 README；
- 将 Pytest 临时目录、缓存和旧临时文件集中到 `D:\htc_qa\pytest-work`，避免系统临时目录权限异常；
- 更新 Pytest 配置并验证测试可正常写入新目录。

## 11. 验证情况

- G1 18 题 × 3 次正式执行；
- G1 瞬时失败坐标定点重试并完成替换；
- G2 18 题 × 3 次正式执行；
- G2 三个失败坐标定点重试并全部成功；
- 报告边界相关测试 16 项通过；
- 原失败 Job 可重新渲染完整报告；
- Pytest 新临时目录配置验证通过；
- 输出目录已按正式结果、重试结果和历史归档分类。

## 12. 当前未完成项与风险

### 12.1 六层质量评分尚未重跑

当前报告已完成执行结果统计，但以下指标不能使用旧批次数据代替：Plan 覆盖率、任务重复率、依赖合理性、正确文档命中率、Evidence Recall@K、噪声比例、Evidence 充分性、Correctness、Completeness、Faithfulness、Answer Relevance、引用覆盖率、引用支持率、来源链接通过率和最终硬门槛通过率。

下一步应直接对本报告中的 G1/G2 有效坐标生成新的六层评分，不再读取旧报告或旧混合批次。

### 12.2 模型配置快照不准确

`frozen_environment.json` 的模型字段没有记录实际服务模型，会削弱复现实验的可信度。正式发布前应修复快照生成逻辑，并在启动批次时同时记录请求模型名、Provider 与 Base URL 标识、Thinking 开关、Temperature、Max Tokens、Timeout、代码提交 SHA、检索与 Embedding 配置。

### 12.3 G1/G2 模型不同

本次对照可作为工程链路基线，但不是严格的算法 A/B 实验。若要形成面向评审的最终质量结论，需要使用同一模型再做一次同配置对照，或将模型差异明确设为实验变量。

### 12.4 Page Index 未测试

G3 需要工具层/数据层提供正式的 Page Index 搜索与层级导航 Provider。本轮不实现、不模拟，也不把缺失算作当前 B 侧失败。

## 13. 交付物索引

| 产物 | 路径 |
| --- | --- |
| 本报告 | `docs/cp2/CP2 Deep Research 全量测试、结果分析与修复报告.md` |
| G1 正式结果 | `outputs/deep_research_benchmark/g1-a95b-formal-18x3-0922` |
| G1 定点重试 | `outputs/deep_research_benchmark/g1-a95b-transient-retry-0922-*` |
| G2 正式结果 | `outputs/deep_research_benchmark/g2-formal-18x3-0921` |
| G2 定点重试 | `outputs/deep_research_benchmark/g2-formal-failed-retry-0922` |
| 评测集快照 | 各正式运行目录下的 `dataset_snapshot.json` |
| 配置快照 | 各正式运行目录下的 `config/frozen_environment.json` |
| 文档清单 | 各正式运行目录下的 `config/documents_manifest.json` |
| 基准输出说明 | `outputs/deep_research_benchmark/README.md` |
| 总输出说明 | `outputs/README.md` |

## 14. 验收结论

本轮“正式执行与故障修复”已完成：G1、G2 均完成 18×3 坐标执行；瞬时故障已按坐标重试，不再污染主要结论；G2 报告边界缺陷已修复并回归验证；G2 有效完成率达到 100%；G1 剩余 8 次失败均为可复现的 `no_relevant_context`；旧的混合批次与旧评分不再作为当前结论。

本轮尚不能宣告“质量硬门槛全部通过”。完整质量验收还需要对这两次新 G1/G2 有效结果执行六层评分，并修复模型配置快照。完成后才能正式给出引用覆盖率、Faithfulness、Answer Relevance 和总硬门槛通过率。
