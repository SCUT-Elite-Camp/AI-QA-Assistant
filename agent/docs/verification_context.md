# 断言核验输入构造

2026-10-19，第一步：独立整理“断言＋已绑定原文上下文”。
组件为 `agent/evidence/verification_context.py`，与绑定解析器、检索器、工具执行器和分类器分开。
构造器本身保持独立、无模型副作用；现已供 Thinking 在线 MiniCheck 和离线检查共用。
Thinking 不通过时回到同一预算循环；Fast 仍只校验绑定，不进入该续答流程。

## 输入与调用

```python
from agent.evidence.verification_context import build_verification_inputs

inputs = build_verification_inputs(
    binding_report,  # validate_grounded_answer 的有效私有绑定报告
    evidence,        # 生成该报告时使用的同一组 Evidence
    max_context_chars=6000,
    token_counter=count_complete_minicheck_input,
    max_input_tokens=512,
)
```

`token_counter(premise, claim)` 由分类器适配层提供，计算完整的
`premise + tokenizer.eos_token + claim`，包括特殊 token，不调用分类模型。
未提供计数器时 `input_tokens=None`，只表示完成结构构造，调用方仍须检查实际模型长度。

构造器不加载文档、发起检索、调用模型、修改断言或判断事实真伪。
调用者必须在模型调用前重新检查当前身份/权限和来源版本/hash。
历史快照可以用于浏览，不因此成为当前可信模型证据。

## 上下文选择

以 `citation_id`、来源身份和 `source_start/source_end` 定位，不重新搜索 quote，
也不根据断言中的业务关键词或相似度挑句子。相同文档的不同 chunk 保持独立身份。

- 正文：保留完整段落、所属标题层级，以及相邻连续的正文段落组。
  标题、表格和代码块构成结构边界；跨段落的限制和否定不会按固定句数/字符窗口丢弃。
- Markdown 表格：保留绑定行、完整行标签、所有列及表头/分隔行。
  保留表格前后正文包络中的说明、单位、条件和脚注。
  一个绑定跨多行就保留所有涉及行；多个绑定指向同表时合并、去重并按原顺序排列。
- 选中行有空单元格时保留整表，避免擅自给合并/继承单元格补主体。
  缺表头的表格片段、仅锚定表头的引用不作为可用文本核验输入。
- 围栏代码整体保留，不把内部的 `#` 或 `|` 当文档标题/表格。
  HTML 表格整体保留，不推测或改写列角色。
- 一个断言的多个来源一起构造 premise，不对片段分别打分后取最高值。
  任一必要支持失效，整个断言输入进入 `needs_review`。

只选择已有 Evidence 内的原文。不能补回检索时未返回的表头/条件，也不声称能自动证明
未绑定的跨章节依赖完整；正确的上下文仍不等于断言有支持。
无明确结构边界的大段文档可能无法在预算内保留，明确交给后续复核。

## 输出与失败

每条 `VerificationInput` 包含：

| 字段 | 含义 |
| --- | --- |
| `claim_id` / `claim` | 原始断言身份与未改写文本 |
| `status` / `reason` | `ready` 或 `needs_review`，以及具体构造失败原因 |
| `sources` | 每个来源的 provenance、原 Evidence 文本 SHA、绑定锚点及所选原文 spans |
| `premise` | 按来源边界标记组合的文本；未就绪时为空 |
| `input_tokens` | 完整模型输入长度；未检查则为 None |
| `context_policy` | 当前策略版本 `bound-structure.v1` |

所有 offset 都以各自 `Evidence.content` 的 Python 字符位置为准，不冒充父文档位置。
每个 span 的 text 都能由对应原 Evidence 的切片原样恢复。
`excerpt_sha256` 是该 Evidence 文本自己的摘要；来源 `content_hash` 原样保留，
不能把父文档 hash 当作 chunk 文本 hash。`[Evidence n]` 是来源边界标记，不是原文事实。

以下情况返回 `needs_review`，不输出部分 premise，也不默认为 supported：

- `binding_reference_changed` / `binding_source_changed`：引用或来源身份与绑定不一致。
- `binding_excerpt_changed`：原文位置越界或该位置的文本已变化。
- `source_lineage_missing`：缺失必要来源身份、hash 或版本，不补造可信 lineage。
- `text_context_unavailable`：原图区域绑定，无法用文本上下文代表图像事实。
- `table_structure_unavailable` / `table_anchor_without_data_row`：表格结构不完整。
- `context_budget_exceeded` / `input_token_budget_exceeded`：完整上下文超过预算。

预算用于拒绝不完整输入，不用于裁掉后半句、其他必要来源或脚注。
`ready` 仅表示输入构造通过已执行的检查，不是分类器结论或源文档真实性保证。
构造结果保持请求私有，不进入 HTTP/SSE、前端诊断或保存的聊天正文。

## 离线构造检查

现有 `python -m eval.claim_verification_acceptance` 新增 `--prepare-only`，
沿用原生来源权限、冻结数据 SHA 和 ACL 副本负例检查，读取提供的冻结正文。
人工核对的 quote/offset 适配为明确命名的 `reviewed-frozen-body` 本地投影，
从已知源版本/hash 推导片段身份，不冒充一次真实问答或模型输出。

该模式只加载固定 MiniCheck 目录的分词器、核验权重摘要并计数，不运行分类器 forward。
输出 `verification-inputs.jsonl` 与 `preparation-summary.json` 到新的 checkout 外目录。
原有不带该参数的分类评测仍消费原冻结 excerpt；本步不改写历史成绩或偷偷替换模型输入。

本次结果与限制见[执行记录](../../docs/testing/quality/verification-context-20261019.md)。

## Online Thinking integration (2026-10-19)

`agent.evidence.gate` now runs this constructor after valid private binding and
current-source checks, then local MiniCheck without truncation (512 tokens).
Unverified or unsupported claims return privately to the same budgeted Agent
loop; model infrastructure failure stops without an unchecked answer. Fast is
binding-only. See [mode contract](chat_mode_contract.md) for configuration,
protocol, release conditions and model limitations. Historical preparation-only
results above remain preparation results.


### 2026-10-20 answer protocol V4

The binding input now contains the independent model `answer` plus private claims.
`claims[].model_answer_spans` are Python character offsets into that original
answer before citation insertion, resolved from exact claim text occurrences.
The verifier still receives the same claim text and source-bound supports; it does
not grade an alternate reconstructed answer. Binding rejects uncovered prose and
overlapping spans before this builder or MiniCheck runs.
