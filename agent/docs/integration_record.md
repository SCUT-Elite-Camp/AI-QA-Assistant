# 联调记录

| 日期 | 测试问题 | 请求体 | 响应体 | trace_id | status | 是否通过 | 问题说明 | 处理人 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-06-22 | 项目 Q1 阶段需要完成哪些功能？ | `{"query":"项目 Q1 阶段需要完成哪些功能？"}`，环境变量 `USE_MOCK_RETRIEVAL=false` | 返回 answer 和 3 条 citations，首条 `doc_id=doc_001`、`chunk_id=doc_001::chunk_0` | `trace-01c663ea` | `success` | 是 | Tool Layer 日志收到同一 `trace_id`：`[RETRIEVAL] trace_id=trace-01c663ea mode=hybrid top_k=5 results=3` | xdj / lhf |
| 2026-06-26 | Week 3 质量控制回归 | `python -m pytest` | 34 个测试全部通过 | 自动生成 | 多状态覆盖 | 是 | 覆盖 `success`、`invalid_query`、`no_relevant_context`、`retrieval_error`、`llm_error`、引用一致性、真实 Tool Layer 冒烟和 trace-aware retrieval logging | xdj / lhf |
