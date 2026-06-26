# vibe 开发记录

本文档记录 Q1 Web 层 vibe 开发过程。每完成一轮小任务后追加记录。

## 当前状态

日期：2026-06-20

当前仓库状态：

- 已有 Vue + Vite 用户层 Demo；
- 已有前端 Mock Agent；
- 已有流式 Mock、异常状态、引用展示、复制回答、清空对话的基础实现；
- 已创建 Java Spring Boot BFF，目录为 `bff/`；
- BFF 已提供 `GET /api/v1/health` 和 `POST /api/v1/chat`；
- BFF 已包含请求/响应 DTO、`query` 非空校验、CORS 配置和成功 Mock response；
- 前端已新增 BFF API client，在 `VITE_USE_MOCK=false` 时请求 Spring Boot BFF；
- BFF 测试已覆盖 health、CORS、chat success 和 blank query，当前 `mvn test` 通过；
- 尚未接入真实 Agent；
- 尚未实现真实 Agent 转发、SSE、异常全场景 Mock、结构化日志和 OpenAPI；
- docs 已补齐 Q1 三阶段计划、接口契约、BFF 轻量 API 文档和 agent 指令。

## 下一步建议

1. 用 `VITE_USE_MOCK=false` 完成 Vue -> Spring Boot BFF -> Mock answer 的第一阶段验收。
2. 保持 Mock 兜底，同时补齐第二阶段需要的异常全场景和交互验收。
3. 等 Agent 接口稳定后，再进入真实 Agent 转发和 SSE 联调。
4. 根据最终接口补充结构化日志、OpenAPI 和部署说明。

## 记录模板

```text
日期：
阶段：
本轮目标：
完成内容：
修改文件：
验证结果：
阻塞问题：
下一步：
```

