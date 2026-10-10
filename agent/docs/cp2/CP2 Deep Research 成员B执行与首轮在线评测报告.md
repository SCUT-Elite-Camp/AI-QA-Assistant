# CP2 Deep Research 成员 B 执行与首轮在线评测报告

## 1. 执行范围

本轮按《CP2 Deep Research 测试与优化双人分工计划》中的成员 B 职责执行，使用真实在线模型，不使用 Mock。

- 模型：`qwen3.7-flash-2026-07-15`
- 文档来源：Confluence RAG 空间中的项目工程记录子树
- 冻结页面：1 个根页面 + 79 个子页面
- 对照组：Fast Chat、Current Deep Research、Deep Research + Page Index
- 首轮规模：3 道 B 侧冒烟题，每组 1 次

首轮是用于验证实验链路和暴露 P0 问题的冒烟运行，不代替正式的“15～20 题 × 3 组 × 3 次”基线。

## 2. 已完成的成员 B 能力

### 2.1 可重复实验链路

已新增批量评测入口，支持：

- 冻结 Git Commit、模型参数、检索配置和文档 Hash；
- 按 case/group/repetition 独立运行；
- 保存成功和失败样本；
- 记录 Research Job、Plan、Progress、Events、Report 和 Citations；
- 采集总延时、任务数、Evidence 数、恢复次数等指标；
- 自动请求 Citation URL 并统计断裂链接；
- 探测 Page Index Provider，不把词法 fallback 伪装成 Page Index。

### 2.2 评测产物

- 评测入口：`agent/eval/deep_research_benchmark.py`
- B 侧冒烟集：`agent/eval/datasets/deep_research_b_smoke.json`
- 冻结配置：`agent/outputs/deep_research_benchmark/config/`
- 修复前在线结果：`agent/outputs/deep_research_benchmark/online-smoke-complete-0914/`
- 来源链接修复后结果：`agent/outputs/deep_research_benchmark/online-source-link-fixed-0914/`

## 3. 首轮在线对照结果

| 组别 | 运行数 | 成功 | 失败 | 平均延时 | 主要结果 |
| --- | ---: | ---: | ---: | ---: | --- |
| G1 Fast Chat | 3 | 0 | 3 | 111.7 s | 检索到 5 条证据后触发 `repeated_tool_call`，以 `agent_limit_reached` 结束 |
| G2 Current Deep Research | 3 | 3 | 0 | 98.9 s | 流程均完成；1 题 `degraded`，2 题 `complete` |
| G3 Deep Research + Page Index | 3 | 0 | 3 | 0.013 s | 能力探测明确返回 `page_index_provider_unavailable` |

此处的“G2 成功”仅代表流程到达终态，不代表已通过效果硬门槛。

## 4. 来源链接 P0 修复

### 4.1 根因

Confluence Cloud API 返回的 `webui` 形如 `/spaces/RAG/pages/...`，导入器原先将它直接拼到站点根域名，生成：

```text
https://tenant.atlassian.net/spaces/...
```

正确的 Confluence Cloud 页面地址应为：

```text
https://tenant.atlassian.net/wiki/spaces/...
```

### 4.2 修复内容

- 规范化 Confluence Base URL，同时兼容站点根地址和已包含 `/wiki` 的配置；
- 保留 `webui` 中已有的 `/wiki`，并为 `/spaces/...` 自动补全 `/wiki`；
- 按冻结 page_id 精确重新同步 80 个目标页面；
- 修正后的 URL 已重新写入 Document JSON 和 Milvus Chunk 元数据；
- 保持原 doc_id 不变，不破坏 SourceManifest。

### 4.3 验证结果

- URL 生成单元测试：4/4 通过；
- 目标页面重同步：80/80 成功；
- 修复前：G2 共 10 个 Citation URL，10 个断裂；
- 修复后：G2 共 11 个 Citation URL，0 个断裂；
- 修复后 3 道在线运行全部完成，平均延时 95.5 s。

## 5. 效果问题与根因

### 5.1 Evidence 只读到开头小段

原始 Document JSON 保存了完整文档。例如 W32 Agent 文档有 8754 个字符、7 个 chunk，但 Current Deep Research 的证据多数停留在 `line:1-5`。这导致报告能看到标题、Sprint 日期和状态，却读不到深层交付内容。

根因层级：`RETRIEVAL_SECTION_MISS` → `EVIDENCE_INSUFFICIENT` → `REPORT_INCOMPLETE`。

### 5.2 版本差异误判为冲突

W32 和 W34 是不同 Sprint，人员与时间字段不同并不自然构成语义冲突。当前冲突检测仍会生成重复的 version conflict。

根因层级：`EVIDENCE_CONFLICT_MISCLASSIFIED`。

### 5.3 信息不足题表现

B-SMOKE-003 要求准确率提升、P95 延时降低和统计显著性的精确数值。报告正确说明现有证据不包含基线、压测或统计参数，没有编造定量结论。

## 6. Page Index P0 状态

当前代码库没有可调用的 Page Index / Hierarchical Navigation Provider。`get_document_outline` 仅出现在 schema/allowlist 或计划文档中，没有实际 Provider 实现。

因此当前只能完成：

- G3 独立切换入口；
- Provider 能力探测；
- 缺失时明确记录 `page_index_provider_unavailable`；
- 禁止将本地词法 fallback 记录为 Page Index 命中。

在 toolset 提供正式 Page Index Provider 前，不能声称 G3 已接入或已完成效果对照。

## 7. 当前硬门槛结论

| 硬门槛 | 当前状态 |
| --- | --- |
| 越权 Evidence = 0 | 冒烟集未发现越权证据，待正式数据集全量验证 |
| 断裂 Citation = 0 | 修复后冒烟集通过（0/11） |
| 无 Evidence 事实结论 = 0 | 待 Claim 级确定性检查 |
| 原文链接打不开 = 0 | 修复后冒烟集通过 |
| 事实 Claim 引用覆盖率 = 100% | 待成员 A 评分 Schema 与正式数据集 |
| Faithfulness ≥ 4/5 | 待正式模型评分 |
| Answer Relevance ≥ 4/5 | 待正式模型评分 |

当前不能宣布整体版本通过交付门槛，因为正式测试集、每题 3 次运行和 Page Index 对照仍未完成。

## 8. 后续输入与执行顺序

1. 成员 A 交付 15～20 题正式数据集、SourceManifest 和评分 Schema。
2. 成员 B 执行 G1/G2 每题至少 3 次，保留全部失败样本。
3. toolset 提供 Page Index Provider 后，成员 B 实现只负责适配的 Search Adapter 并运行 G3。
4. 根据正式运行结果完成六层评分、硬门槛检查和现场演示环境。
