# Chat 断言支持数据与整条答案拒绝验证

> 历史实施记录：本次自评分数与阈值方案已按用户要求撤销。当前行为和后续方案见[断言绑定与独立校验方案](claim-binding-verification-plan-20261015.md)。下文保留当时实际结果，不代表当前验收。

日期：2026-10-15。范围：Fast / Thinking 的有原文证据答案；不改变 Research。

## 实现

- 答案模型同一次生成输出 `answer` 和 `claims[].{text,supports[]}`；每个支持项含引用编号、原文片段和 0～1 自评分数。
- 有证据的最终生成、Thinking 修复和兜底请求传 `response_format={"type":"json_object"}`。Fast 仍只有一次生成请求，不增加重试、外部评审或修复调用。
- 后端拒绝异常 JSON、缺失断言、未覆盖的实质正文、不存在的引用/原文、低分支持及凭月日片段补出的年份。阈值 `ANSWER_SUPPORT_MIN_SCORE=0.8`，含等号；非法配置启动失败。
- 通过的片段绑定原文字符位置、文档/块 ID、evidence_ref、版本和 hash；图片使用归一化区域，文本和图片协议不可互换。
- 内部报告留在请求级 `answer_grounding`，不进入 ChatResponse、SSE、前端诊断或保存的消息。拒绝时答案和引用均为空。
- Thinking 的修复只在新支持数据有效且原有完整性保护通过时替换原答案；最终出口再次校验最终文本，兜底不能绕过。

分数来自答案模型自评，不是独立语义判定或正确率。代码校验原文真实性和映射结构，并提供年份精度保护；不能保证高分片段在所有语义情况下确实蕴含断言。

## 自动化

最终全量 Agent 测试：`1001 passed`，34.49 秒；保留两项既有依赖弃用警告。使用独立外部 `--basetemp`，不占用其他任务的临时数据库。
验证包含 Fast 单调用、JSON/SSE 私有数据隔离、分数边界、伪造片段、漏标断言、非法配置、图片区域、Thinking 修复与最终兜底，以及 HTTP JSON 参数透传。
测试替身明确模拟新协议，不是模型质量验收。

## 实际模型与资料复核

使用隔离运行目录、真实企业文档、现有 Milvus、实际 embedding、Groq `openai/gpt-oss-20b`、Web session/CSRF 和 native Confluence 权限。未修改原索引或原运行数据。

固定问题：

> In Preliminary Ideas, who completed Multi-Query Fusion, on what date, and how many queries can it use? 请用中文回答，并标注引用。

生成前已人工核对原文：Jiaxing Dai；July 30；最多三条查询。该行没有年份。文档是项目资料，不是 `[Eval KB]` fixture。

| 请求 | 返回状态 | 总耗时 | 生成调用 | Codex 复核 |
| --- | --- | --- | --- | --- |
| 仅旧引用编号检查，修改前 | success | 32.264 秒 | 1 | 错补 2023 年，旧检查仍通过 |
| 新私有数据协议，首次 | quality_validation_failed | 13.297 秒 | 1 | 引用与正文覆盖无效，整条拒绝 |
| 增补格式示例后 | quality_validation_failed | 15.906 秒 | 1 | 返回格式不合格，整条拒绝 |
| 启用提供方 JSON 输出约束 | quality_validation_failed | 11.687 秒 | 1 | JSON 合法，但正文漏引用、补出 2023 年且自评 0.98，整条拒绝 |

三次新协议请求的 SSE 和保存消息均未包含私有 `claims`、`support_score` 或 `image_region` 字段。最后一次请求可在本地聊天 `686a9db5-3f11-4a57-8001-62b392d60950` 查看拒绝结果。
原始模型结果、服务端报告、请求与 SSE 仅保存在忽略的外部运行目录：
`C:/Users/Hola/AppData/Local/AI-QA-Assistant/runtime/fast-evidence-20261015-154814/claim-grounding-native-json/`。

上述为同一已见问题的修复后验证，不能算未见 holdout，也不能据此声称速度提升或回答质量达标。
本次真实请求证明拒绝边界与单调用预算生效，尚未获得真实模型正向通过或重复稳定性验收；Thinking、个人库和原图的真实验收未在本次案例中执行。
