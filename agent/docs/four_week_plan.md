# 四周计划

## 第 1 周

- Agent 基础框架
- `/api/chat` 入口
- 参数校验
- `trace_id`
- Mock Retrieval
- Mock LLM
- Prompt Builder V1
- Answer Formatter
- 接口契约

## 第 2 周

- Retrieval Adapter
- Context Assembler
- Prompt 模板优化
- LLM Client
- Answer Generator
- citations 组装
- Mock / real 模式切换
- Tool Layer `SearchTool.search()` 冒烟通过

## 第 3 周

- `no_relevant_context` 已覆盖空检索和低相关检索。
- `retrieval_error` 已覆盖检索异常和真实 Tool Layer 缺失。
- `llm_error` 已覆盖 LLM 异常和空输出。
- `invalid_query` 已在入口校验阶段返回。
- 幻觉抑制 Prompt 已强化，只允许基于检索上下文回答。
- answer 与 citation 一致性检查已在 AnswerFormatter 中实现。
- 日志链路已记录阶段、检索模式、top_k、检索数量、状态和错误类型。

## 第 4 周

- Web 联调接口已稳定，`/api/chat` 返回普通 JSON。
- 已新增 `/api/chat/stream` 作为 Q1 SSE 演示接口。
- 已完成全链路测试、异常场景测试、CORS 测试和 SSE 事件测试。
- 已新增 Demo 问题集 `mock/demo_questions.json`。
- 已新增 Week 4 验收脚本 `scripts/run_week4_acceptance.py`。
- 已整理 Web 联调指南、Week 4 报告和 Q1 交接说明。
