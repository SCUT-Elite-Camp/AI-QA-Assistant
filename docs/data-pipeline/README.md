# 数据处理管线

[返回文档导航](../README.md)

| 文档 | 性质与用途 |
| --- | --- |
| [当前数据处理管线](DATA_PIPELINE.md) | 当前结构化解析、OCR、文本视图、chunk 与 schema 契约 |
| [表格处理整合记录](table-processing-integration-20261012.md) | 2026-10-12 整合范围和验证限制 |
| [Confluence 全量重拉与观察](confluence-refresh-20261014.md) | 2026-10-14 来源和索引同步记录；不等于问答质量通过 |
| [Fast 基线评测](../testing/quality/fast-evaluation-20261014.md) | 来源更新后的真实问答结果及修复复测 |
| [管线详解](../../data-pipeline/docs/数据处理管线详解.md) | 组件分层设计与早期示例 |
| [Confluence 导出](../../data-pipeline/docs/Confluence导出.md) | 组件导出说明 |

运行与迁移先读[隔离运行手册](../access-evidence/access-evidence-runbook.md)。实际 embedding 维度必须匹配集合；新投影与新索引使用独立路径和集合，保留原始数据。
