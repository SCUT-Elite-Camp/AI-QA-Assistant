# CP2 Research Core 评测基线

该基线用于比较确定性 Planner、后续可选 LLM Planner 以及 Worker 改动。任何 Planner 都必须通过同一组控制面、证据和恢复门禁。

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
