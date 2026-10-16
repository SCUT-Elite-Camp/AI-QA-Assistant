# 项目文档导航

本目录按模块组织跨层文档。组件内部实现仍在各组件的 `docs/` 和 README 中维护。

## 从哪里开始

| 任务 | 入口 |
| --- | --- |
| 了解项目、启动本地服务 | [项目 README](../README.md) |
| 理解身份、来源权限与证据链 | [访问架构](access-evidence/access-evidence-architecture.md) |
| 对接 Web / Agent / Toolset | [当前接入契约](access-evidence/access-evidence-integration.md) |
| 配置隔离环境、复现真实验收 | [运行手册](access-evidence/access-evidence-runbook.md) |
| 查阅验收结果与未完成事项 | [测试与验收](testing/README.md) |

## 模块目录

| 目录 | 内容 |
| --- | --- |
| [access-evidence](access-evidence/README.md) | 当前跨层访问架构、接口契约、运行手册与权限演示 |
| [data-pipeline](data-pipeline/README.md) | 解析、表格/OCR、索引契约与来源同步记录 |
| [data-persistence](data-persistence/README.md) | 持久化职责、优化记录及组件入口 |
| [knowledge-navigation](knowledge-navigation/README.md) | Section / Wiki 导航设计、接入边界与历史实现报告 |
| [personal-library](personal-library/README.md) | 个人库运维、部署、人工验收与实现记录 |
| [memory-context-plan](memory-context-plan/README.md) | Memory 分单元施工计划、契约及测试夹具 |
| [testing](testing/README.md) | 整合交接、回答质量、UI 复测与历史修复证据 |
| [archive/q1](archive/q1/README.md) | 2026 年 7 月 Q1 历史需求与 API 规格 |

## 阅读和维护约定

- 当前身份、权限、来源范围、接口和运行配置以访问与证据模块为跨层入口；模块专项契约补充其细节。日期报告只证明报告所述版本和环境，不自动代表当前分支已验收。
- 历史规格、实施计划、测试模板和实际测试结果分开阅读。运行成功、机器质量、人审及重复稳定性分别记录，未填写的验收表不算通过。
- 新文档放入对应模块，并同步模块索引；只有跨模块导航保留在本目录根部。通用契约使用稳定文件名，单次报告保留日期和环境说明。
- 移动文件时同步相对链接、根 README、AGENTS 与组件引用。Memory 夹具仍在原路径，由前端契约测试直接读取。
- 历史分数、失败记录和本机证据路径保持原意。凭据、源站导出、数据库及模型文件不进入文档目录。

本次目录整理迁移了 26 份原根目录文档，保留原文件名。原 `docs/<文件名>` 现在位于上表对应模块；其中 PR63 交接移至 `testing/integration/`，Fast 评测移至 `testing/quality/`，网页复测移至 `testing/ui/`。
