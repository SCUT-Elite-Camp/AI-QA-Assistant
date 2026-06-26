# Docs 使用说明

这个目录是 Q1 Web 层 vibe 开发时的项目事实来源。开始开发前先读 `agent.md`，再读三阶段计划和接口契约；每次改动后同步更新相关文档，避免代码、Demo 目标和接口约定脱节。

## 读取顺序

1. `agent.md`
   - 给人和 AI agent 的项目指令。
   - 明确 Web 层边界、技术栈、不能越界的部分和当前优先级。
2. `q1-three-phase-plan.md`
   - Q1 到 2026-07-10 的三阶段任务分工。
   - 第二阶段任务较轻，用于补齐交互和异常，给真实联调留缓冲。
3. `api-contract.md`
   - Vue 调用 Java Spring Boot BFF、BFF 调用 Agent 的接口契约。
   - 开发时优先保持这个文件稳定。
4. `q1-web-architecture-refinement.md`
   - 细化架构方案。
   - 说明 RAG 闭环、Web 层、Agent 层、数据处理管线和 Apache Tika 入库位置。
5. `july-demo-delivery-scope.md`
   - 2026-07-10 Demo 的必做、加分、暂缓功能和最终验收清单。
6. `vibe-guide.md`
   - 每次 vibe 开发时应该如何拆任务、改代码、验收和更新文档。
7. `vibe-log.md`
   - 当前开发记录和下一步任务。

## vibe 时 docs 下面应该写什么

每次开始一个 vibe 小循环前，先更新或确认：

- 当前目标属于哪一个 Q1 阶段；
- 本次只做哪些功能；
- 会影响哪些接口；
- 是否需要 Mock；
- 验收方式是什么。

每次完成一个 vibe 小循环后，至少检查：

- `q1-three-phase-plan.md` 中对应任务是否完成；
- `api-contract.md` 是否与代码一致；
- `vibe-log.md` 是否记录了完成内容、阻塞点和下一步；
- 如果 Demo 范围变化，更新 `july-demo-delivery-scope.md`；
- 如果架构边界变化，更新 `q1-web-architecture-refinement.md`；
- 如果给 AI agent 的开发规则变化，更新 `agent.md`。

## 文档维护原则

- 文档优先写具体事实，不写空泛目标。
- 接口字段、状态枚举、错误提示必须和代码保持一致。
- Q1 必做内容不能混入加分功能，避免 2026-07-10 前失焦。
- Web 层只负责 Vue 前端和 Java Spring Boot BFF，不直接实现检索、LLM、向量存储和 Apache Tika 解析。
- 当真实 Agent 未完成时，Mock 必须能兜底演示。

