# 真实 Confluence 产品验收集 v1

## 目标与边界

在 `agent-dev` 可独立交付的范围内，验证用户是否拿到正确、完整、可追溯的回答，
而非只验证任务状态为 completed。入口是公开 HTTP API：G1 普通问答与 G2 Research
创建 → 计划 → 批准 → 执行 → 报告。暂不依赖 dev 集成、Web 或跨团队统一验收。

问题来自已冻结的真实 RAG 空间资料，经人工设计为代表性任务；**不是生产用户日志**。
v1 是针对本批缺口的开发验收集，不是未见测试集，也不证明整体产品质量。
来源属于历史快照，不能把 W30/W34 或 CP2 表中状态当成当前项目现状。

## 用例与验收

配置：`agent/eval/datasets/product_acceptance.v1.json`。
继承 `eval/deep_research_a/datasets/cases.v1.json` 中的问题、允许文档和关键原文位置，
来源版本与内容哈希由原 `source_manifests.v1.json` 校验。
PA-001 单独定义简化问题；运行时为派生问题单独计算 question_sha256，保留原始 source_case_id。

| 用例 | 用户任务 | 必须回答的内容 |
|---|---|---|
| PA-001 | 单文档事实查询 | W30 Agent 的四项指标，逐项对应 9/5/1/3 |
| PA-002 | 跨文档比较 | W30 与 W34 四项指标，以及方向明确的四项变化 |
| PA-003 | 跨章节追溯 | 三项能力的 commit 映射、三个新增 Python 文件 |
| PA-004 | 条件判断 | 原始数据、5+1=6、两项条件分别核验及结论 |
| PA-005 | 表格与空值 | 指定里程碑状态；空白必须为未记录，不作推断 |
| PA-006 | 抵抗相似文档干扰 | 正确周次/模块的作者、日期、提交总数 |
| PA-007 | 受限资料不足 | 明确无法确认，不能猜测未提供资料的精确数字 |

每条机器预验收必须同时满足：API 运行成功或合理无资料结果；所有逐点检查为真；
模型裁判 faithfulness 和 citation_support 均至少 4/5；证据文档无越界；
已返回证据的 locator 与摘录可在冻结原文匹配。没有证据时不虚构匹配率。
关键章节召回率单独报告，不用“有一个引用”代替答案正确性。

裁判使用同供应商模型，属于**初步自动判定**。需要伙伴逐题复核原文、回答与引用，
特别注意裁判检查布尔值和 rationale 可能不一致。没有人工签字前不得标为最终产品验收通过。
本轮检查的是显式文档范围，不等同于验证真实登录用户的 Confluence ACL。

## 已针对本批用例修复

- Research 以 chunk 为候选，允许读取同一文档多个章节；兼顾文档多样性。
- 结构化文档标题词降权，避免每个 task 重复文档标题导致只读标题章节；拆分代码文件标识符，
  让 `intent classifier` 能匹配 `intent_classifier.py`。纯文本旧演示仍保留标题匹配。
- 模型驱动 Research 每个 task 最多读三个候选，仍受已批准 max_actions 和总预算限制；
  非模型演示保留原来两候选默认值。
- 规划和报告沿用 LLM_THINKING_MODE，避免 DeepSeek 推理输出挤占正文预算并静默回退模板。
- 不再把仅周期/版本数字不同的比较任务按 0.95 文本相似度强判重复。
- 普通问答通过证据门控后进入无工具回答回合，防止重复同一次检索直到预算耗尽。
- 比较门控先保留各检索查询的命中记录，再做展示证据去重；修复“都检索到了却被判缺一方”。
- 显式 BM25 的纠偏仍用 BM25 扩大候选，避免无向量服务时不必要地切到 vector。
- 资料不足不再被意图提示词当作能力不支持，交由受限检索后的证据判断。
- 报告检查截断、五段结构与引用编号范围；至多一次结构重写，不通过仍回退验证材料。
  这不是语义完整性证明，引用是否真正支持结论仍需要验收。
- 超长冲突展示摘要限制到 2000 字符，完整原文保留在证据及 citation 中，避免大表格使渲染失败。
- 普通知识问答的检索策略上限为 10；具有显式 `doc_ids` 硬范围时仍保持这一有界窗口，避免用户已经限定文档后只读到摘要章节。
- 报告生成把用户请求的模块、周期和冻结资料范围视为硬边界；资料只覆盖相邻模块时明确拒答，不把相邻模块数字写进结论。

## 复现

使用独占测试 checkout，勿对正在服务用户的目录运行。准备现有 Python 环境及已冻结 BM25、
processed documents、Confluence metadata。真实文档、密钥、SQLite 与运行输出均不提交。
只读取原文快照，不触发在线 Confluence 同步或写回。

```powershell
$config = Import-PowerShellDataFile '<你填写的本地 key.psd1>'
$env:LLM_API_KEY = $config.DEEPSEEK_API_KEY
$env:LLM_API_BASE = 'https://api.deepseek.com'
$env:LLM_MODEL = 'deepseek-flash'
$env:LLM_THINKING_MODE = 'disabled'
$env:LLM_TIMEOUT = '90'
$env:QUERY_REWRITE_ENABLED = 'false'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:DEBUG = 'false'
$env:PYTHONUTF8 = '1'
python agent/eval/product_acceptance.py --repo '<测试 checkout>' --documents '<原文目录>' --metadata '<confluence_metadata_RAG.json>' --bm25 '<冻结 bm25_index.pkl>' --output '<新的输出目录>' --port 8013 --repeats 2
# 针对修复后的失败项快速复跑：在上一条命令基础上使用新的输出目录，并追加：
# --groups G1 G2 --case-ids PA-006 PA-007 --repeats 2
```

可执行 API 模型 ID 为 `deepseek-flash`；不能仅凭营销名称断言精确模型 revision。
G1 请求 BM25；G2 使用 manifest-scoped 本地 JSON 检索与原文读取。**不称作 hybrid 验收**，
也不需要 Docker/Milvus。旧代码在 BM25 纠偏阶段切 vector 的行为作为基线缺陷保留。

脚本记录问题、来源哈希、commit/diff、模型、检索配置、Python/依赖版本，
保存原始 API 返回和逐点裁判。新的执行器还保存 implementation.patch 与 evaluator.py。
G2 只传 document_ids，不额外传知识库空间：当前 SourceScope 的空间与文档是并集，
误传 RAG 会把整个空间纳入研究。
finally 停止测试服务，并按字节恢复原 BM25 与 chat_history，写 restoration.json。
强制结束整个 Python 进程仍可能阻止 finally；保留 `.original` 备份供恢复。

完成后生成逐题对照及失败定位提示（不覆盖原始裁判）：

```powershell
python agent/eval/summarize_product_acceptance.py --before '<修复前输出>' --after '<修复后输出>' --output '<新对照目录>'
```

## 2026-09-21 本地机器预验收结果

| 批次 | G1 | G2 | 说明 |
|---|---:|---:|---|
| 修复前基线（每题 1 次） | 4/7 | 0/7 | API 均成功，但 Research 回答未达到逐点、忠实度与引用门槛 |
| 修复后全量检查（每题 2 次） | 12/14 | 13/14 | 28 次 API 执行均成功；遗留 PA-006 G1 两次、PA-007 G2 一次 |
| PA-006 最终定向复跑 | 2/2 | — | 检索窗口策略修复后，正确周次与模块的关键章节均召回并通过 |
| PA-007 最终定向复跑 | — | 2/2 | 报告硬化资料范围后，两次均拒绝用相邻 Agent 数字回答 Web 问题 |
| 当前代码全量确认（每题 2 次） | 14/14 | 14/14 | 28 次均运行成功并达到机器预验收门槛 |

修复前、修复后全量检查及两组最终定向复跑均使用真实冻结 Confluence 原文。
最终定向结果补充而不篡改此前全量记录；随后已在同一当前工作树重新执行完整两轮，
得到独立的 G1 14/14、G2 14/14。提交前代码回归为 415 passed。机器预验收已覆盖
本批已知失败，仍需伙伴做逐题人工签字；合并后的发布级数字应在目标 commit 上再执行一次。

## 历史基线

旧 A 侧 frozen_baseline 不替换成此次 DeepSeek 配置。G1 的历史 Runner 增加 P0 合并 commit
和 Git blob 哈希定位，保留原 Windows 文件哈希；验证历史源不再要求当前开发中的 Runner
与旧基线逐字节相同。新结果使用自己的 environment.json，不能用旧配置给新运行背书。

本地自动测试（历史资产测试需设置 DR_EVAL_DOCUMENTS_DIR、DR_EVAL_METADATA_PATH）：

```powershell
python -m pytest agent/tests/unit agent/tests/integration eval/deep_research_a/tests -q
```
