# 11 功能开关、安全与可观测性导航页（不可执行）

本文件不是 `<XX>`。由于配置、BFF 降级和 Agent policy 位于不同工作区，原跨层 `11` 已拆为：

1. `11-Agent`：[`11-agent-flags-security-observability.md`](11-agent-flags-security-observability.md)
2. `11-Web`：[`11-web-flags-security-observability.md`](11-web-flags-security-observability.md)

固定顺序是 `11-Agent → 审查 → 11-Web → 审查`。二者均以 `09-Agent`、`09-Web` 审查通过为前置；
`12` 只在两个单元都通过后开始。首版不实现 Redis：`MEMORY_CACHE_ENABLED=true` 必须安全拒绝，
不能安装、导入或连接任何 Redis 客户端。
