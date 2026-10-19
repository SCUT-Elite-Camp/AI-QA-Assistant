# 测试、验收与历史证据

[返回文档导航](../README.md)

本目录按整合交接、回答质量和 UI 分类。根部保留既有 2026-10-02 至 10-10 的修复/分支报告及 `evidence/`，便于追溯原有证据链。

2026-10-15 起，全系统默认测试采用英文问题、断言、普通资料与预期答案/报告（`en-US`）。
语言/Unicode 专项显式标注；历史非英文轮次保留，翻译后另建复测版本，见[评测规则](quality/evaluation-policy.md)。

## 专项结果

| 文档 | 日期与范围 |
| --- | --- |
| [PR63 整合验收](integration/pr63-integration-acceptance.md) | 2026-10-09 基线、真实权限链路、G1/G2 质量与未完成门槛 |
| [Optimization 整合检查](integration/optimization-consolidation-20261019.md) | Thinking 与 Research harness 整合、依赖阻断/完整审稿/权重绑定修复、639 项 Agent 和 318 项前端回归 |
| [Fast 基线](quality/fast-evaluation-20261014.md) | 2026-10-14 当前镜像、冻结问题、原始失败及修复复测 |
| [Fast 优化与英文复测](quality/fast-optimization-20261014.md) | 通用修复、阶段结果；完整英文回答等待Groq配额恢复 |
| [Codex逐题重评](quality/codex-answer-scoring-20261014.md) | 原问答四维评分、项目/样例分组、无外部Judge调用 |
| [Confluence 英文化](quality/confluence-english-20261014.md) | 74 页面全量核对、17 页面及 21 附件翻译、原管线同步；旧评测冻结需另建新轮次 |
| [断言核验英文复测](quality/claim-verification-english-20261015.md) | 126 对全英文断言、NLI/MiniCheck 结果及全系统测试默认语言 |
| [MiniCheck 误判分析](quality/minicheck-error-analysis-20261015.md) | 当前选型、3 条误放行/3 条误拒、原文与 35 项英文输入诊断 |
| [断言核验输入构造](quality/verification-context-20261019.md) | 第一步独立组件，126 对英文构造检查及明确的超长输入限制 |
| [MiniCheck 实际核验](quality/minicheck-structured-verification-20261019.md) | 真实分类推断、114 对共同样本对照与 12 对未核验；效果和耗时限制 |
| [Thinking 与单次生成](quality/thinking-single-generation-20261019.md) | 同模型 21 题真实尝试、9 题共同答案比较、格式/上下文失败及每日额度阻断 |
| [Thinking 预算循环与 MiniCheck 接入](quality/thinking-agent-loop-20261019.md) | 统一 Agent 循环、核验失败续答、632 项回归；真实 MiniCheck 正反例，完整真实问答受 Groq 日额度限制 |
| [Confluence 与网页复测](ui/ui-retest-20261012.md) | 2026-10-12 来源更新、真实问答和网页复测 |
| [选区问答 UI](ui/selection-ui-retest-20261012.md) | 2026-10-12 选区工具栏、抽屉与保存交互 |
| [流式展示复测](ui/stream-presentation-retest-20261012.md) | 2026-10-12 正文渐进展示和动画 |
| [桌面 UI 复测](ui/desktop-ui-retest-20261013.md) | 2026-10-13 输入框、定位与桌面交互 |

## 历史修复与分支记录

| 文档 | 用途 |
| --- | --- |
| [周报：10-02 至 10-08](repair_test_weekly_20261002_20261008.md) | 多阶段修复与测试历史 |
| [修复报告：10-09](repair_test_report_20261009.md) | 当时回归及原始证据索引 |
| [高风险修复复测](high_risk_repairs_retest_20261009.md) | 高风险案例与后续关联 |
| [重复测试条件](high_risk_conditions_repeat_20261009.md) | 复测条件和边界 |
| [剩余修复：10-10](remaining_repairs_20261010.md) | 剩余项、最终复测和证据摘要 |
| [Agent 基建 PR 说明](pr_agent_dev_infra_20261010.md) | PR 范围、验证和评审入口 |
| [整合合并冒烟](integration_merge_smoke_20261009.md) | 当时合并检查 |
| [整合分支比较](integration_branch_comparison_20261009.md) | 本地/远程分支差异与报告归属 |

## 复现和结果解释

真实验收的环境和命令见[运行手册](../access-evidence/access-evidence-runbook.md)。模块专项记录另见[表格整合](../data-pipeline/table-processing-integration-20261012.md)、[来源同步](../data-pipeline/confluence-refresh-20261014.md)和[个人库人工验收](../personal-library/personal-library-manual-acceptance.md)。

运行通过、机器质量、人审和重复稳定性各自独立；参与修复的题目不能继续称作未见留出集。报告按各自版本、环境与来源快照阅读，不把不同轮次择优汇总为一次通过。

部分旧报告引用的 `outputs/` 本机产物未包含在本 checkout；旧报告还引用了缺失的 `frontend/tests/ReasoningFloatingWindow.test.ts`。这些是整理前就存在的证据可用性限制，原引用保留，不能据此补写或改写历史成绩。已提交的 `evidence/remaining-20261010/` JSON 摘要仍保留原路径。


2026-10-15 测试维护：移除已删除维护脚本对应的 `test_pdf_evaluation.py`、
`test_milvus_live_check.py`、`test_safe_reindex.py`，以及仅锁定旧镜像仓库的
`test_docker_compose_config.py`。解析、向量 provenance、版本发布失败保护和数据隔离
继续由现有管线/存储/Toolset 测试覆盖；这些删除不修改历史验收记录。
存储单元测试显式绑定模拟集合名，不依赖本机 `.env` 的企业集合设置；
真实存储测试按 Data Persistence README 的显式开关运行，不与模拟测试结果混计。
