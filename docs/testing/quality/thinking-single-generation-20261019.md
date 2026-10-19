# Thinking 与单次生成实测（2026-10-19）

## 结论与有效范围

本批已返回的答案没有显示单次生成存在明显的事实质量劣势。两条链路共同返回答案的 **9 题均合格**，单次生成平均分 99.44，Thinking 100；这点差异不足以证明多调用带来稳定提升。

21 题均实际尝试了两条链路，共保存 42 份结果。第 14 题开始，当前 Groq 账号达到 `openai/gpt-oss-120b` 的每日 200,000 tokens 额度，后 8 题两组均未释放答案，全部记为**未评分**。本次没有完成这 8 题的答案质量比较，尤其不能推断维护期限、health/ready 和日期问答的效果。

Thinking 确实能恢复部分格式错误，但也增加了全文补读超限和额外表述的风险。本轮未启用 MiniCheck 在线拦截或“分类器拒绝后重答”；不能用本轮结果评价该闭环的收益。

## 试验设置

- 从既有 126 对英文分类器样本提取 **21 个原始问题**；没有把人工构造的错误断言交给回答模型。这些问题和来源已经检查过，属于已见复测。
- 两组答案模型都为真实 Groq `openai/gpt-oss-120b`，`reasoning_effort=high`，temperature 0.1，完成预算 4096 tokens，包含推理消耗。Thinking 的正常查询准备模型仍为配置中的 `openai/gpt-oss-20b`。
- 单次组使用现有 `FastPipeline`，仅在独立评测进程中注入相同的 120B/high 客户端，一次 HTTP 尝试，无生成修复。它**不代表默认 20B/low Fast 的质量或延迟**。
- Thinking 组使用现有 `ThinkingPipeline`、QueryUnderstanding、Runner、工具预算和格式恢复逻辑。两组均为无历史请求，关闭首次标题生成，不提供参考答案或金标准事实。
- 请求均为 hybrid、TopK 5、相同的 11 篇企业文档范围。Thinking 的政策和模型仍可改变实际检索参数、改写问题、补读全文；实测初次搜索常用 TopK 10。两条链路的提示、检索及上下文不同，因此这不是仅改变调用次数的严格消融实验。
- 实际使用本地 BGE-small-en-v1.5（384 维）、Milvus、BM25 和本地英文 reranker。新集合为 `test_disposable_thinking_english21_20261019_v1`，71 个已有解析块；未重新运行解析器。
- 数据、Web 权限数据库副本、BM25 和输出都在 checkout 外。使用真实 PermissionService、当前 Confluence 原生权限及 AccessGuard 的模型/工具/释放边界检查。显式本地 ACL 拒绝探针在标记的数据库副本中执行并恢复，原数据库未修改。
- 直接执行真实 Agent 业务链路，不经过 Web/BFF 会话、CSRF、持久化消息和 HTTP Reader。本次不属于完整端到端产品验收。

原英文数据 SHA-256：`8f03ac6b631ff794d18b7c546e906e864108342311a9a8e8ce18dfe9885af3c1`。
21 题冻结文件 SHA-256：`9fb33570c5f0c359244ccbf4635d2322412e8c0d879df58a44891e6249a8c5bc`。
问题、来源文件 hash、模型参数和代码指纹均在主轮推断前记录；主轮结束的代码指纹检查通过。

## 数量、质量与耗时分开统计

以下只统计每日额度阻断前的 Q01–Q13，保留其中原始失败：

| 指标 | 同模型单次生成 | Thinking |
| --- | ---: | ---: |
| 尝试问题 | 13 | 13 |
| 实际返回答案 | 12 | 10 |
| 返回答案的断言绑定有效 | 12/12 | 10/10 |
| Codex 内容评审合格 | 12 | 9 |
| JSON 格式失败且无答案 | 1 | 0 |
| 请求大小超限且无答案 | 0 | 3 |
| Provider HTTP 请求数，含失败及正常规划 | 13 | 53 |
| 内容完整性修复 `answer_repair_attempted` | 0 | 0 |
| 成功响应上报的 tokens | 35,882 | 90,685 |
| 总墙钟耗时，含限流等待 | 309.79 s | 1,230.16 s |
| 其中测试节流等待 | 109.05 s | 985.56 s |

两组共同返回答案的 9 题为 Q02、Q03、Q05、Q06、Q09、Q10、Q11、Q12、Q13：

| 共同样本指标 | 同模型单次生成 | Thinking |
| --- | ---: | ---: |
| 合格 | 9/9 | 9/9 |
| 四维平均分 | 99.44 | 100.00 |
| 扣除测试节流等待的耗时中位数 | 14.15 s | 18.68 s |

耗时仍包含检索、权限复核和模型请求；没有验证生产延迟 SLA 或重复稳定性。成功响应的 usage 不包含未上报 usage 的错误请求，不能作为完整账单；账号额度也不能仅由这些 usage 归因。

全部 21 题的记录为：单次组 21 次 Provider 请求，Thinking 88 次。每日额度导致的 8 题未评分不计为语义失败，也不以 0 分填补。单次 Q04 的 JSON 生成格式失败记应用回答失败 0 分；没有据此判断其事实内容。不同分母的全组均分不用于主比较。

## 逐题结果

按照[评测规则](evaluation-policy.md)，Codex 阅读实际答案、绑定片段及冻结原文，评正确性、完整性、来源忠实度、引用质量；没有调用外部 Judge API。完整性按问题实际要求判断，不机械要求旧分类器样本中的所有附加事实。例如 Q03 没有要求枚举 SSE 事件名。

| ID | English question | Single pass | Thinking | 评审说明 |
| --- | --- | --- | --- | --- |
| Q01 | According to Local Setup, which runtimes belong to Agent and Web? | 100 | 未评分：413 | 单次正确；Thinking 补读后超限，无答案 |
| Q02 | What does Local Setup say health checks and dev login establish? | 100 | 100 | 均覆盖 readiness 限制和 loopback-only 设置 |
| Q03 | Does the SSE wire format guarantee incremental production? | 100 | 100 | 均明确不保证增量生产；Thinking 经格式恢复 |
| Q04 | How does BFF handle insufficient evidence and interrupted streams? | 0：格式失败 | 82.5 | Thinking 答全核心行为，但额外组件归因超出原文 |
| Q05 | What does Retrieval Strategy say hybrid retrieval and mixed sources do? | 100 | 100 | 均正确描述 RRF 和多来源不可替代 |
| Q06 | What are the documented limits of hybrid fallback and ranking scores? | 100 | 100 | 均区分降级与双后端验收、排名与事实支持 |
| Q07 | Which stores are authoritative and which can be rebuilt? | 100 | 未评分：413 | Thinking 全文补读后的请求超限 |
| Q08 | What are the documented attachment expiry and lineage rules? | 100 | 未评分：413 | 单次正确回答冻结文档；Thinking 请求超限 |
| Q09 | What conditions grant enterprise and personal-library access? | 95 | 100 | 单次附加服务启动条件，轻微混合运行条件与授权条件 |
| Q10 | Which dependencies and Reader checks are retained? | 100 | 100 | 均答全依赖及权限、版本、hash、原文片段检查 |
| Q11 | How does the enterprise pipeline export and retract source content? | 100 | 100 | 均区分只读导出、本地写索引和撤回清理 |
| Q12 | What do partial indexing and export limitations mean? | 100 | 100 | 均解释部分索引和非实时导出 |
| Q13 | How are evaluation conclusions and holdouts separated? | 100 | 100 | 均区分运行/权限/引用/完整性及修复题/留出集 |
| Q14 | What are the limits of mocks, machine judges, and mutating probes? | 未评分：429 | 未评分：429 | 每日额度阻断 |
| Q15 | Who may edit team folders, and what does the RAG team do? | 未评分：429 | 未评分：429 | 每日额度阻断 |
| Q16 | What are the stated maintenance deadlines and bot schedule? | 未评分：429 | 未评分：429 | 每日额度阻断；未验证 3 天/2 天关系 |
| Q17 | Which processes does Compose start, and which state must be shared? | 未评分：429 | 未评分：429 | 每日额度阻断 |
| Q18 | What do health/readiness endpoints and isolated ports mean? | 未评分：429 | 未评分：429 | 每日额度阻断；未完成此题的 health/ready 对照 |
| Q19 | Who owns browser identity and enterprise access authority? | 未评分：429 | 未评分：429 | 每日额度阻断 |
| Q20 | What scope and lineage decisions apply to Research and Wiki? | 未评分：429 | 未评分：429 | 每日额度阻断 |
| Q21 | Who completed Multi-Query Fusion, on which date, and with how many queries? | 未评分：429 | 未评分：429 | 每日额度阻断；未验证是否仍会补写年份 |

Q04 Thinking 四维为正确性 3、完整性 4、忠实度 3、引用质量 3，总分 82.5。最后一句为：

> BFF validates evidence before persistence and on later reads using AccessGuard and CitationChecker.

所绑定的片段只说明 BFF 在持久化和后续读取时校验，未支持 `using AccessGuard and CitationChecker`。同文档 Implementation 将这些 Python 组件列在 Agent 侧，并为 Web 列出另一组工具。该额外归因说明**绑定成功不能替代语义支持检查**。

Q09 单次组授权核心事实均正确；将 Local Setup 中的私有服务启动要求合并为授权条件，忠实度记 3，其余维度 4，95 分。Thinking 正确分开了这些条件。该小幅表述差异不能视为稳定的多轮收益。

## 观察到的链路问题

### 全文补读让请求膨胀

Q01、Q07、Q08 在补读后收到 HTTP 413，服务商报告 Requested 分别为 10,779、14,672、12,949 tokens，超过该账号的 8,000 TPM 请求额度。这些不是可评分的答案。

Q01 读取 Local Setup 一篇文档，工具消息达到 23,209 字符。原始正文约 2,663 字符，消息同时包含全文、约 14,100 字符的 chunks 序列化及额外 Citation evidence。重复正文和元数据进入工具历史，造成膨胀。此处观测的是账号请求额度拒绝，没有测定模型上下文窗口边界。

### 格式恢复不同于事实修正

Q01–Q13 中有 7 次 `tool_use_failed`：模型把 `answer_grounding_v3`、`answer_grounding` 或 `json` 当作不存在的工具调用。现有 Runner 随后走干净证据上下文的答案生成，成功返回正文。这是格式/协议恢复，不是 MiniCheck 指出无依据断言后的修正。

单次组 Q04 收到 `json_validate_failed`，严格一次调用因此没有恢复机会。Thinking 同题恢复出了可读答案，同时增加了上述无依据归因。重答有恢复价值，也可能改变或增加事实表述，不能仅用次数判断更好。

全部 22 份成功答案的绑定报告均有效，但 `semantic_validation=not_performed`；主轮未触发内容完整性修复。当前 Thinking 多次调用不能等同于“生成—语义核验—针对错误重答”。

结束后另行核对了这 22 份英文答案的 65 条断言、74 个支持绑定：原文位置精确匹配，公开引用均对应已接受 Evidence。42 份原始结果 hash、11 份原始来源文件及所选代码指纹检查通过。这些机械检查仍不替代上述语义评审。

## 限制与后续判断

- 当前数据支持保留单次生成作为速度优先路径；未观察到共同样本的核心事实损失。严格一次调用会放弃格式恢复机会。
- Thinking 应先解决工具消息中的正文/元数据重复和答案 JSON 被误当工具的协议问题，再比较有界语义修复的成本与收益。本轮没有修改这些业务逻辑。
- 之前 MiniCheck 的误放行多数来自人工构造反例，不能把本次未生成反例说成“Thinking 修复了误放行率”。维护期限、health/ready 以及实际年份回归本次受额度阻断，仍未验证。
- 来源是保留 hash/version 的历史导出。部分文档仍描述旧附件服务、扫描、章节工具或历史浏览回源策略。本次只评价对冻结资料的回答，不以这些描述证明当前实现，也没有改写历史资料或历史评分。
- 独立人审、重复稳定性、未见问题和完整前端体验均未完成。没有将模型/检索/权限替换为 fake 来补足结果。

## 本机证据与复现边界

主轮目录：`D:/AI-QA-Assistant/claim-verification-20261019/thinking-comparison-v2/`。

- `protocol.json`、`questions.frozen.json`：推断前冻结的设置和问题。
- `EN-Q*.{single_pass_same_model,thinking}.json`：真实 Provider 响应、usage、最终执行轨迹、Evidence、私有断言绑定及公开答案。
- `codex-review.v1.json`：42 份结果的逐题评审、原始结果 hash、实际答案和已审阅绑定。
- `review-protocol.v1.json`、`comparison-summary.json`：评分规则、未评分处理及机械汇总。
- `acl-negative.json`、`index-preparation.json`、`results-manifest.json`：拒绝探针、独立索引及原始输出 hash/代码未变检查。
- `final-audit.json`：原始结果 hash、英文答案、断言位置、公开引用身份及原始来源未变检查。

执行器为同级 `run_thinking_comparison_paced.py`，日志为 `thinking-generation-v2.log`。最初分钟额度不足的探测轮保留在 `thinking-comparison-v1/`，未替换主轮失败，也不计作稳定性验收。重跑必须另建结果版本，不覆盖本轮文件。

观测器有一项限制：它保留了 Runner messages 列表的引用，较早调用的 `request.messages` 可能反映列表最终状态，不能作为逐调用不可变输入快照或用于精确重放。实际 Provider 响应、usage、模型参数、最终执行轨迹、Evidence 和绑定不受影响；本次按这些记录评审。后续观测应在调用时深拷贝消息。该限制已记录在评审协议中。

本轮没有改产品代码或前端接口；没有为文档变更重跑全套单元测试，也不把此前的 pytest 结果标成本轮新验证。
