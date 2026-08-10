# CP2 Agent 测试、问题与架构演进汇总

> 更新时间：2026-08-09
> 范围：CP2 Agent 层本地开发与在线评测
> 说明：不同阶段的样本数和模型配置不同，数据用于阶段内诊断，不应直接视为严格同分布排行榜。

## 1. 汇总目的

本文按“发现问题 → 尝试方案 → 数据结果 → 架构变化”的顺序，记录 CP2 Agent 从初始串行链路到当前分层模型、复合任务拆分和证据质量控制链路的演进。

测试覆盖：

- 意图识别、澄清、查询改写和 Query Preparation；
- QueryPlan、IntentPolicy、ToolRegistryAdapter 和 ToolExecutor；
- Evidence Gate、Corrective Retrieval、Answer Completeness 和 Citation Check；
- 普通知识问答、复合比较问题、本地知识库质量和端到端耗时；
- qwen3.7-plus、qwen3.6-flash、qwen-flash 与本地 BGE 的分层调用。

## 2. 初始基线：流程正确，但串行 LLM 调用过多

### 发现问题

初始 Query Understanding 将意图识别、澄清、改写和规划拆为多次串行模型调用。端到端知识库测试中还出现证据不足、Policy Limit 和回答阶段重复调用工具等问题。

### 尝试方案

- 建立 14 条核心组件问题和 8 条本地知识库质量问题；
- 增加 QueryPlan、Evidence Gate、Corrective Retrieval、Citation Check 等可观测字段；
- 对重复工具调用和最大检索次数增加有界停止机制；
- 将测试结果输出为 JSON、CSV 和统一 Excel 报告。

### 数据结果

`local_kb_full_online.json`：

| 指标 | 结果 |
|---|---:|
| 组件意图准确率 | 92.9% |
| 澄清准确率 | 100% |
| Query Understanding 平均耗时 | 42.03 秒 |
| 质量题成功回答率 | 75.0% |
| 要点阈值达标率 | 50.0% |
| 引用有效率 | 62.5% |
| Policy Limit 发生率 | 25.0% |
| 质量题平均端到端耗时 | 91.73 秒 |

### 架构变化

流程从“模型自由循环”调整为受 QueryPlan 和 IntentPolicy 控制的有界执行：

```text
ConversationMemory
  → Query Understanding
  → QueryPlan
  → IntentPolicy
  → ToolRegistryAdapter / ToolExecutor
  → Evidence Gate
  → 最多一次 Corrective Retrieval
  → Answer Generation
  → Citation Check
```

## 3. Query Understanding 级联优化

### 发现问题

四个理解环节完全串行会放大延迟；一次性将所有环节合并到一个 Prompt，又存在 Prompt 过长和单点失败扩散风险。

### 尝试方案

采用级联设计：

1. 意图识别独立执行；
2. Reference Resolution、Clarifier、Query Rewriter 和 Query Planning 合并为 Query Preparation；
3. Query Preparation 主模型使用 qwen3.6-flash；
4. 保留强模型回退机制；
5. 不进行模型微调。

### 数据结果

| 阶段 | 样本 | 关键结果 |
|---|---:|---|
| 原串行理解 | 14 | 平均 42.03 秒 |
| 级联理解 | 14 | 平均 25.84 秒，降低约 38.5% |
| 复合题 Query Preparation | 5 | 意图准确率 100%，任务拆分准确率 100%，平均 20.29 秒 |

### 架构变化

```text
用户问题
  → Intent Router
  → Query Preparation
       ├─ 指代解析
       ├─ 澄清判断
       ├─ 独立问题改写
       └─ sub_queries / filters
  → QueryPlan
```

## 4. 级联 + BGE 混合意图识别

### 发现问题

意图识别仍可能每题调用在线模型，增加耗时和费用；BGE 模型路径未正确配置时会静默回退在线 LLM。

### 尝试方案

- 使用本地 `bge-small-zh-v1.5` 对意图示例做向量匹配；
- 高置信度且 margin 足够时直接接受本地结果；
- 边界样本回退在线模型；
- 扩充项目领域意图示例；
- 在服务启动时预热并在同一 Worker 中缓存模型；
- `/ready` 增加 `intent_ready`。

### 数据结果

| 指标 | 结果 |
|---|---:|
| 14 题意图准确率 | 100% |
| Query Understanding 平均耗时 | 22.55 秒 |
| BGE 热启动编码耗时 | 约 10–36 ms |
| 3 条定向知识问题意图在线调用 | 从 3 次降为 0 次 |
| 3 条定向题端到端平均耗时 | 51.18 秒 |

### 架构变化

```text
高精度规则
  → BGE 意图相似度
       ├─ 高置信度：直接输出意图
       └─ 低置信度：在线 LLM 回退
  → Query Preparation
```

规则只处理少量明确表达，BGE 与 LLM 回退共同降低规则误判风险。

## 5. 复合问题拆分与并行检索

### 发现问题

“总结并比较 CP1 和 CP2”不能只用一个宽泛查询。串行检索多个主体会增加耗时，证据混合后也难以判断两侧是否都被覆盖。

### 尝试方案

- comparison 和复杂 knowledge_qa 生成 `sub_queries`；
- comparison 的多个主体并行调用同一个 `search_documents`；
- 合并和去重 Evidence；
- Evidence Gate 检查 bilateral coverage；
- 仅对缺失目标执行一次定向 Corrective Retrieval；
- 回答后执行语义完整性检查。

### 数据结果

`compound_latest_end_to_end_online.json` 的 5 条复合题：

| 指标 | 结果 |
|---|---:|
| 意图准确率 | 100% |
| 任务拆分要点达标率 | 100% |
| 成功回答率 | 80% |
| 引用有效率 | 80% |
| 重复工具调用率 | 0% |
| Policy Limit 发生率 | 0% |
| 平均端到端耗时 | 78.23 秒 |

其中 1 题为工具错误，说明复合任务成功率仍受检索工具稳定性影响。

### 架构变化

```text
复杂问题
  → Query Preparation 生成 sub_queries
  → 多目标并行检索
  → Evidence 合并与去重
  → Evidence Gate 检查目标覆盖
  → 定向纠正检索（最多一次）
  → 复杂答案生成
  → Answer Completeness
  → Citation Check
```

## 6. 重复工具调用与 Policy Limit 修复

### 发现问题

模型已经拿到检索证据后仍可能再次请求相同工具，最终触发 `repeated_tool_call` 或 Policy Limit。原因不是单纯知识库内容少，而是模型在工具历史上下文中重复选择工具。

### 尝试方案

- Evidence Gate 接受证据后隐藏工具 Schema；
- 使用干净的 evidence-only Prompt 直接生成答案；
- 不重放容易诱发重复调用的 assistant tool-call 历史；
- 同一批比较检索完成后停止消费额外搜索调用；
- 保留最大迭代、重复调用和检索预算限制。

### 数据结果

后续本地质量与复合题批次中：

- 重复工具调用率稳定为 0%；
- Policy Limit 发生率从初始质量测试的 25% 降为 0%；
- 证据不足时返回明确停止原因，不再无限循环。

## 7. Answer Completeness 分层

### 发现问题

所有问题都调用 LLM 做完整性检查会显著增加延迟；但完全取消检查会让比较、总结和多要点回答出现漏答。

### 尝试方案

- 单目标答案只做本地有效引用检查；
- comparison、summarization、存在子问题或多环节范围的任务使用 qwen3.6-flash 做语义完整性检查；
- 仅在检查失败时进行一次答案修复；
- 检查失败时保留原答案，避免质量门禁自身导致请求失败。

### 数据结果

- 单目标问题不再产生 Answer Completeness 在线调用；
- 复杂题完整性检查约 3.7–5.3 秒；
- 复合题批次完整性检查覆盖成功答案；
- 当前仍存在“完整性模型按用户问题判断、离线验收按隐藏工程要点判断”的口径差异。

## 8. 快慢答案模型分层

### 发现问题

Plus 答案生成是端到端耗时的主要来源。普通问题若全部使用 Plus，平均答案生成可达到 31 秒以上；但过早将多要点题路由到 Flash 会降低术语和要点覆盖。

### 尝试方案

当前本地实验路由：

```text
简单问题
  条件：无 sub_queries、无纠正检索、不是比较/总结、不是多环节范围
  → qwen-flash
  → 本地引用检查

复杂问题
  条件：comparison / summarization / 任意 sub_query /
        corrective retrieval / multi_aspect_scope
  → qwen3.7-plus-2026-05-26
  → qwen3.6-flash 完整性检查
```

Flash 失败会自动回退 Plus。

### 数据结果

两条无子问题定向题的同题对比：

| 指标 | Plus 历史结果 | qwen-flash | 变化 |
|---|---:|---:|---:|
| 平均端到端耗时 | 52.46 秒 | 31.51 秒 | 降低约 39.9% |
| 平均答案生成耗时 | 34.51 秒 | 10.06 秒 | 降低约 70.8% |
| 成功回答率 | 100% | 100% | 不变 |
| 引用有效率 | 100% | 100% | 不变 |

但是这两题后来被确认包含多环节要求，不应作为纯简单题代表。加入 `multi_aspect_scope` 后，两题重新走 Plus，平均端到端耗时为 52.95 秒。

## 9. 要点测试低分诊断与修复

### 发现问题

Flash 定向测试中两题成功回答、引用有效，但严格要点阈值为 0%。进一步检查发现三类原因：

1. 评测器只做原始字符串包含，无法识别 `CitationChecker` 与 `Citation Checker`；
2. 测试数据的部分中文同义词曾存在编码问题；
3. API 流程题没有检索到 `API_CONTRACT`，生成模型缺少精确模块名证据。

### 尝试方案

- 对答案和术语做 Unicode、大小写、标点和空格规范化；
- 增加 CamelCase、snake_case 标识符拆词匹配；
- 补齐中英文概念别名；
- 在每个要点中记录 `matched_term` 和 `match_type`；
- Prompt 要求技术契约题保留类名、字段名、状态值、模块名和 API 名称；
- 新增 `multi_aspect_scope`，防止多环节问题错误走 Flash；
- 不把测试答案要点直接注入生成 Prompt，避免数据泄漏。

### 数据结果

使用已有 Flash 答案离线重评分：

| 问题 | 原始匹配 | 修复评测器后 |
|---|---:|---:|
| API 流程 | 2/6 | 4/6 |
| Corrective Retrieval | 2/6 | 2/6 |

这证明 API 题存在部分评测误判，而 Corrective Retrieval 确实存在真实漏答。

最新两题在线回归：

| 指标 | 结果 |
|---|---:|
| 成功回答率 | 100% |
| 意图准确率 | 100% |
| 引用有效率 | 100% |
| 重复工具调用率 | 0% |
| Policy Limit 发生率 | 0% |
| 预期文档命中率 | 50% |
| 平均端到端耗时 | 52.95 秒 |
| API 流程要点 | 2/6 |
| Corrective Retrieval 要点 | 3/6 |

两题都正确进入复杂模型和语义完整性检查，但 API 题仍未命中 `API_CONTRACT`，说明生成侧优化不能替代正确召回。

## 10. 当前完整流程

```text
用户请求
  → ConversationMemory
  → Hybrid Intent Router
       ├─ 高精度规则
       ├─ BGE 本地分类
       └─ 在线 LLM 回退
  → Query Preparation（qwen3.6-flash）
       ├─ 指代解析
       ├─ 澄清判断
       ├─ 查询改写
       └─ sub_queries / filters
  → QueryPlan（公共契约不变）
  → IntentPolicy
  → ToolRegistryAdapter
  → ToolExecutor
  → 单查询或复合问题并行检索
  → Evidence 标准化
  → Evidence Gate
       └─ 不足时最多一次 Corrective Retrieval
  → 答案复杂度路由
       ├─ 单目标：qwen-flash
       └─ 复杂/多环节：qwen3.7-plus-2026-05-26
  → Answer Completeness
       ├─ 单目标：本地引用检查
       └─ 复杂任务：qwen3.6-flash 语义检查
  → Citation Check
  → ConversationMemory 写回
  → 最终响应
```

## 11. 当前结论与后续计划

### 已验证有效

- 级联 Query Understanding 显著降低理解阶段耗时；
- BGE 能减少明确意图问题的在线分类调用；
- 复合比较问题可以拆分并行检索；
- 重复工具调用率和 Policy Limit 已降为 0%；
- qwen-flash 对真正单目标问题具有明显速度优势；
- 新要点评测器比纯字符串匹配更可解释。

### 当前主要瓶颈

1. 正式契约文档可能被会议记录和总览文档挤出候选结果；
2. Answer Completeness 与离线工程要点的判断口径仍需继续对齐；
3. 当前普通题测试集中仍混有多环节问题；
4. Plus 答案生成仍是复杂问题的主要耗时来源；
5. 本地模型、个人百炼模型名称和 API Key 不能作为团队默认配置提交。

### 建议下一步

1. 工具层优化正式契约文档的标题匹配、候选召回和文档类型排序；
2. 新建纯单目标简单题集，重新进行 Plus/Flash 同题 A/B；
3. 将完整性检查所需的“回答方面”显式来源于 Query Preparation，而不是隐藏测试答案；
4. 完整项目阶段再统一建设真实数据库/API、并发、多 Worker 和回溯评测框架。

## 12. 对应原始报告

- `eval/reports/local_kb_full_online.json`
- `eval/reports/local_kb_cascaded_components_online.json`
- `eval/reports/local_kb_cascaded_hybrid_intent_online.json`
- `eval/reports/compound_latest_end_to_end_online.json`
- `eval/reports/compound_query_preparation_qwen36_flash_online.json`
- `eval/reports/local_quality_snapshot_cascaded_bge_tiered_simple3_online.json`
- `eval/reports/local_simple_answer_routing_qwen_flash_targeted_online.json`
- `eval/reports/local_multi_aspect_prompt_metrics_retest_online.json`
