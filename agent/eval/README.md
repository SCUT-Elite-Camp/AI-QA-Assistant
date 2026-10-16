# CP2 Research Core 评测基线

## 默认评分方式（用户指定，2026-10-14）

2026-10-15 起，全系统默认测试使用英文问题、断言、普通资料和预期答案/报告（`en-US`）。
默认产品验收 profile 为 `datasets/product_acceptance.en.v2.json`，新增整合探针为
`datasets/integration_holdout.en.v2.json`；旧冻结数据与成绩保留，英文译本属于已见复测。
明确的多语言/Unicode 专项另行标注，详见评测规则。

由Codex逐条核对实际问答、原文和引用，再给分及汇总；不调用Groq或其他外部
Judge API。Groq可继续作为被测回答模型。结构/契约检查和数学汇总仍可用脚本。
评分维度、未评分处理及项目/外部样例分组见[评测规则](../../docs/testing/quality/evaluation-policy.md)。

## 真实产品验收入口（2026-10-09）

后续 Core 场景是隔离契约测试，不是实际模型质量结果。真实验收使用 `prepare_integration_runtime.py`、`integration_boundary_acceptance.py` 和 `research_product_acceptance.py`，从 `agent/` 目录以 `python -m eval.<module>` 启动，参数和配置见[运行手册](../../docs/access-evidence/access-evidence-runbook.md)。

三类来源/混合问答验证实际 BFF 会话、CSRF、解析、索引和 Reader；附件病毒扫描已按当前产品要求移除。G1/G2 使用相同冻结 Confluence 来源与 hybrid 检索，7 题为 repair-informed 回归，3 题生成前冻结。权限负例必须显式提供 ACL 拒绝的 `--forbidden-doc-id`，不是题目 out-of-scope 文档。所有失败保留；机器评分不代替人审和重复稳定性。结果见[整合报告](../../docs/testing/integration/pr63-integration-acceptance.md)。

该基线用于比较确定性 Planner、后续可选 LLM Planner 以及 Worker 改动。任何 Planner 都必须通过同一组控制面、证据和恢复门禁。

## MiniCheck 断言核验（2026-10-15）

用户选定仅保留 MiniCheck-DeBERTa-v3-Large，评测入口已移除其他模型分支与选择参数。
`python -m eval.claim_verification_acceptance` 验证本地 MiniCheck，
不接入 Chat，不调用生成式或外部 judge API。
它只验证“给定原文能否支持断言”，不是完整问答、检索或 BFF 的端到端验收。
当前误判及诊断见[MiniCheck 分析](../../docs/testing/quality/minicheck-error-analysis-20261015.md)。

依赖放在隔离环境；模型权重、人工核对的病例、源文档、SQLite 与输出均在 checkout 外。
病例须有逐条 Codex 标签/理由、原文位置、源文件 SHA-256，且在推断前冻结；
默认要求病例声明英文原文与英文断言；仅显式语言专项使用 `--allow-non-english`。
开发集与 holdout 按文档分开，实际模型错误回归另列。SHA 不匹配、未授权来源、
原文漂移、未完整加载的权重或超过 512 token 的输入均停止，不静默截断。

正常 native 环境中，从 `agent/` 运行，例如：

```powershell
python -m eval.claim_verification_acceptance `
  --model-dir D:/claim-eval/models/minicheck `
  --dataset D:/claim-eval/private/cases.json --dataset-sha256 <已冻结SHA256> `
  --documents D:/claim-eval/documents --permission-db D:/claim-eval/web.sqlite `
  --user-id <已绑定账号> --forbidden-doc-id <真实文档ID> `
  --split dev regression --batch-size 4 --threads 4 --single-benchmark `
  --output D:/claim-eval/private/run-new
```

沿用正常运行手册的组件 `PYTHONPATH`、原生账号/站点绑定与凭据环境；不向命令行传明文密钥。
模型目录须含 `verified.json`（repo、固定 revision、weight_file、sha256），
runner 会重新验证本地权重，不下载或执行远程自定义代码。MiniCheck 使用官方 EOS 拼接输入，
使用固定训练分类决策，不根据已见病例调阈值。

每个模型 forward 前及结果结束时重新核对当前本地/native 权限与冻结原文。
`--forbidden-doc-id` 指向真实存在的文档；runner 先确认原来源授权，然后仅在
带标记的可丢弃 SQLite 副本中撤去本地授权并检查 ACL 拒绝，finally 恢复副本。
这证明本地 ACL 拒绝边界，不冒充原生 Confluence 拒绝或线上撤权竞态验收；原数据库不改动。

结果保留逐条原生标签、误放行/误拒绝、语言与错误类型分组、原文/病例 hash 和模型版本。
MiniCheck 的“不支持”不被伪装成可区分矛盾/证据不足的三态。
单条耗时由六个开发病例各两次测量，排除预热、权限/版本检查和模型加载；
batch 均摊吞吐不得解释为单请求延迟。小型人工构造样本不能代表自然错误发生率或整个中文场景。

当前默认语言对应的结果见[全英文复测](../../docs/testing/quality/claim-verification-english-20261015.md)；
前一轮混合语言结果保留为历史记录，不能替代英文轮次的结论。

## 一键执行

```powershell
.\.venv\Scripts\python.exe agent/eval/research_core_baseline.py
.\.venv\Scripts\python.exe -m pytest agent/tests/unit/test_research_contract.py agent/tests/unit/test_research_control_plane.py agent/tests/unit/test_research_progress.py agent/tests/unit/test_research_worker_reporting.py agent/tests/integration/test_research_control_plane_api.py agent/tests/integration/test_research_demo_scenario.py agent/tests/integration/test_research_quality_baseline.py agent/tests/integration/test_research_vertical_slice_e2e.py -q
```

第一个命令输出机器可读 JSON；第二个命令执行完整 Research 核心回归集。

## 硬门禁

| 指标 | 要求 |
|---|---:|
| SourceManifest 范围外证据 | 0 |
| 引用覆盖率 | 1.0 |
| 断裂引用 | 0 |
| 未支持结论写入报告 | 0 |
| 重复 Evidence ID | 0 |
| 重复 Event Key | 0 |

耗时、动作数、工具调用数和恢复次数先作为基线记录，不在首版设置拍脑袋阈值。积累 CI 数据后再确定 P50/P95 目标。

## 场景矩阵

| 场景 | 自动化覆盖 |
|---|---|
| 单一/一致来源正常完成 | `test_manual_api_entry_dispatches_to_traceable_report` |
| 固定语料结果可重复 | `test_fixed_local_fixture_e2e_is_repeatable_and_traceable` |
| 新旧政策冲突并降级 | `test_policy_conflict_demo_exercises_the_cp2_core_chain` |
| 必要资料不足并降级 | `test_insufficient_material_completes_as_degraded` |
| 冲突证据不得被强行选边 | `test_conflicting_evidence_is_disclosed_not_selected` |
| 错误 Manifest Hash 拒绝批准 | `test_approval_binds_exact_plan_version_and_manifest_hash` |
| 计划修订后旧批准失效 | `test_plan_revision_supersedes_old_version_and_requires_fresh_approval` |
| 创建/规划阶段重启恢复 | `test_restart_recovers_created_job_and_reuses_frozen_manifest` |
| Evidence 后崩溃且不重复 | `test_restart_after_evidence_does_not_duplicate_evidence` |
| Report 后崩溃且只有一份报告 | `test_restart_after_report_persistence_finishes_finalize` |
| 不安全检查点明确失败 | `test_restart_without_safe_checkpoint_fails_explicitly` |
| 外部来源范围被拒绝 | `test_api_cannot_create_job_from_external_source_scope` |

## LLM Planner 接入规则

LLM Planner 只产生候选 `ResearchPlan`，不得绕过 Schema Validator、SourceManifest、预算、工具白名单和人工批准。接入前后都运行上述命令，并比较 JSON 中的质量门禁、动作数和耗时。
