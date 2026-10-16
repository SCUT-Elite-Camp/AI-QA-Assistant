# 访问与证据

[返回文档导航](../README.md)

| 文档 | 用途 |
| --- | --- |
| [访问边界与证据链路](access-evidence-architecture.md) | 当前跨层安全架构、来源边界与 lineage |
| [Web / Agent / Toolset 接入契约](access-evidence-integration.md) | 当前浏览器/BFF、内部接口及流式行为 |
| [隔离联调运行与复现](access-evidence-runbook.md) | 环境变量、隔离存储、启动、真实验收与排查 |
| [权限隔离与 Confluence 空间演示](权限隔离演示与Confluence空间隔离.md) | 本地 ACL 演示；不代表全角色原生权限验收 |
| [PR63 整合交接](../testing/integration/pr63-integration-acceptance.md) | 2026-10-09 基线、历史成绩与剩余门槛 |

浏览器身份属于服务端会话；企业授权为本地 ACL 与 Confluence 原生读取权限交集。Research 仍仅支持企业 Confluence；Wiki 导航自身 lineage 完备前保持隔离。具体配置以运行手册和忽略的本机凭据为准。
