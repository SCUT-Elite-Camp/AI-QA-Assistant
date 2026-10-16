# Fast / Thinking 模式契约

日期：2026-10-15。

状态：两条运行链路已拆分。`agent/chat/fast.py` 实现 Fast，`agent/chat/thinking.py`
拥有 Thinking 的规划与工具循环；`Agent` 负责统一身份、分派及响应组装。
本文同时记录目标契约与当前落地范围，未完成事项见文末。

## 模式是用户选择的执行契约

- `fast` 执行 Fast 链路，不因问题措辞、子查询、来源类型或工具失败隐式进入 Thinking。
- `thinking` 执行 Thinking 链路，不根据问题看起来简单而隐式进入 Fast。
- 两条链路可以共享工具、检索、模型客户端、证据结构、权限和来源复核；各自拥有执行流程、提示词、模型绑定与调用预算。
- 旧 `auto` 按用户确认兼容到 Thinking，不再做复杂度路由；省略模式仍默认 Fast。
- Thinking 执行下文定义的规划与有界工具循环，不套用 Fast 的一次生成限制。具体限制沿用现有服务端配置；统一总调用预算仍待实现，见文末。
- Deep Research 仍是独立功能，不属于这两条 Chat 链路的自动升级目标。

## Fast 执行顺序

```text
请求与当前身份校验
  → 根据请求结构、选定来源及文件类型确定工具
  → 原问题直接检索 / 固定工具解析、OCR
  → 将返回文档块、工具结果、必要的原图与原问题打包
  → 当前来源复核
  → 固定 Fast 答案模型，一次生成
  → 无额外模型调用的断言支持、格式、引用和来源复核
  → 返回结果
```

### 原问题直接检索

- 搜索文本直接使用用户本轮问题，保留原始含义；不调用模型做改写、翻译、意图识别、规划或查询扩展。
- 不拆子问题，不生成替代搜索词，不执行 HyDE、模型路由或基于复杂度的升级。
- 对请求明确选中的每类来源执行预先确定的检索动作；混合来源可以各检索一次，使用相同原问题。
- 无知识库来源且无文件时，不执行检索；知识库关闭时，不以其他规则重新开启它。
- 使用返回的文档块；允许按既有分数去重、排序、限定数量及上下文预算，不增加独立重排模型。
- 不为补全答案继续扩展相邻块、自动翻页或进行纠偏检索。权限、版本/hash 核验所需的原文读取属于来源复核，不用于额外扩展模型上下文。
- 引用片段仍须来自同一当前授权原文。截取、去重和上下文裁剪不得改写事实或伪造来源。

### 工具由程序确定

工具调用不经过模型，不向答案模型暴露工具 schema，也不处理模型返回的工具调用。
规则基于服务端认可的请求结构、文件类型和选定来源，不能由问句推导出新的授权范围。

| 请求输入 | Fast 固定动作 |
| --- | --- |
| 企业知识库 | 用原问题检索当前授权范围 |
| Personal Library | 用原问题检索当前 owner/KB 范围 |
| 当前会话/Topic 文件 | 读取或检索当前允许文件的解析结果 |
| 图片或扫描内容 | 读取已有解析/OCR 结果；必要时执行非生成式 OCR |
| 需要视觉理解的图片 | 将当前授权原图与其他上下文放入最终 Fast 模型的同一次请求 |
| 纯对话，检索关闭且无文件 | 用原问题和允许的会话上下文直接生成 |

当前实现读取已经持久化的解析/OCR，剔除独立 `vision_analysis` 结果，不在问答时重新解析。
企业检索调用 `SearchTool.search_direct`，不执行标题/日期范围推断或章节补充。
Fast 的可信内部字段 `retrieval_sources` 可显式选择来源（包括空数组）；省略时查询可用的企业与个人库，
自动带入会话允许文件。显式选中的来源及选中文件属于必需来源；默认可用但空的个人库不阻断企业回答。
该字段不提供授权，也不替代 Thinking 原有的结构化 SourceIntent。

同一工具处理多个请求文件时允许有界批处理或并行；不形成模型观察结果后再选择工具的循环。
并行工作必须传播请求级权限上下文。缺少必要工具、处理失败或超出固定预算时明确结束，不回退到 Thinking。

### 严格一次生成模型调用

正常答案生成只有一次生成模型请求；在此之前因鉴权、工具、无证据等原因结束时可以是零次。
本轮请求引发的所有同步、后台和辅助生成调用均计入预算，不能通过换接口或异步执行隐藏。

```text
本轮生成调用总数 = 答案 + 改写/规划 + 视觉识别 + 修复/评审 + 标题/摘要等辅助调用
本轮生成调用总数 ≤ 1；正常生成时，答案调用 = 1，其余项 = 0
```

- 图片工具只做解析/OCR，不能再调用视觉大模型、VLM 或生成式识别 API；视觉理解由最终答案请求一并完成。
- 最终 Fast 模型不具备所需多模态能力时明确报告能力不足，不另调视觉模型、不切换模式，也不只凭 OCR 假装已理解图像内容。
- 检索所需 embedding 和非生成式 OCR 是检索/解析计算，不计入生成调用次数，但应分别记录其次数与耗时；它们不得内部转调生成模型。
- 选定 Fast 答案模型后不再按问题复杂度挑模型，不进行失败重试、模型回退、第二次答案修复或生成式事实评审。
- 标题使用确定性问题截取/现有标题；本轮不另调模型生成标题、Memory 摘要或 Fact。允许打包既有且已核验的历史/Memory，不先用模型改写或总结它们。
- 模型响应中的工具调用不触发任何执行；格式异常按失败处理。

## Fast 输出与失败边界

- JSON 和 SSE 必须驱动同一条 Fast 业务流程，只改变结果交付方式。
- 缺少任一必需来源的有效证据时，不拿另一来源冒充；资料不足时明确返回不足状态，不增加检索或生成轮次。
- 引用编号规范化、裁剪未用引用及来源身份检查可以用确定性代码完成；校验失败不调模型修复。
- 不以追求速度为由跳过当前身份、原生权限、文件作用域、有效期、版本/hash、来源依赖或释放前复核。
- 需要在正文释放前完成的校验仍须先完成；是否缓冲正文由输出校验决定，不复制出另一套流式问答流程。
- 模型、工具或校验失败必须如实终止，不把失败包装成成功答案或另一个模式的结果。
- 既有响应结构、来源证明及 Reader 绑定继续适用。图片能力不足返回 `unsupported`，引用校验失败返回 `quality_validation_failed`。
- 图片原文引用使用 `content_kind=file`，以当前文件 SHA-256 和 evidence version 绑定；普通片段仍为 `excerpt`。Reader 读取原图时再次验证同一身份、版本和 hash。

### 答案断言与原文绑定（Fast / Thinking 共用）

有编号原文证据时，答案模型同一次生成输出严格 JSON，请求传递
`response_format={"type":"json_object"}`：

```json
{"claims":[{"text":"可见答案。","supports":[{"citation_id":1,"quote":"对应原文片段"}]}]}
```

原图引用用 `image_region=[left,top,right,bottom]` 归一化区域替代 quote。
不再生成模型自评分数，已删除相关字段、阈值配置与临时的年份判断规则。
模型只输出带支持片段的断言列表，不再同时维护独立 answer 字段；服务端按断言顺序组装正文并从 supports 生成引用编号；
模型若已带合法引用则避免重复插入，未在正文重复输出编号不影响绑定通过。

程序只检查绑定结构：每个正文段落直接来自带绑定的 claim.text、来源编号存在、
quote 确实存在于对应证据（允许空白归一化）、文本与图片片段类型一致。
通过后记录断言在编号前拼接正文中的字符位置、原文片段的位置、文档/块 ID、evidence_ref、版本和 hash。
`answer_grounding.valid` 仅代表绑定有效，报告另标记
`validation_kind=binding`、`semantic_validation=not_performed`；不表示语义支持已经成立。

格式错误、缺绑定、虚构片段或额外未绑定的 answer 字段仍整条拒绝，返回 `quality_validation_failed` 和空答案。
支持数据只保存在请求级内部结果，不进入 ChatResponse、SSE、前端诊断或保存的消息。
证据答案与推理先缓冲，通过结构、引用和来源检查后只释放正文。
Fast 不重试或修复，仍最多一次生成。Thinking 修复和兜底也必须有有效绑定，
失败修复不能替换原答案；最终出口检查正文与已绑定文本一致。
纯对话没有编号证据时仍走文本协议。

语义蕴含、原子性和资料本身是否正确尚未由本模块判断。
后续独立校验的研究方案见[断言绑定与独立校验方案](../../docs/testing/quality/claim-binding-verification-plan-20261015.md)，
尚未接入新的校验模型或外部 judge。

## Fast 实施后的验收标准

以下为验收断言；当前自动化覆盖见文末，不等于真实模型质量或性能验收。

| 场景 | 必须验证 |
| --- | --- |
| 普通知识库问题 | 检索接收原问题；返回块进入答案上下文；生成调用一次 |
| 比较、完整流程等复杂措辞 | 不改写、不扩展、不切换 Thinking；仍只有一次生成 |
| 图片有 OCR | 工具由文件输入触发；OCR 结果进入上下文；无独立视觉生成调用 |
| 图片需要视觉理解 | 原图与问题进入同一次多模态答案调用 |
| Fast 模型不支持所需图片能力 | 明确失败，不追加生成调用 |
| 企业、个人库、附件混合 | 尝试全部请求来源，保持各自权限范围，不让模型选工具 |
| 某一必需来源无证据或失败 | 不用其他来源替代，不调用 Thinking |
| 生成失败或返回工具调用 | 不重试、不换模型、不执行模型要求的工具 |
| 缺引用或引用不合法 | 只执行确定性处理，无法通过则失败，无第二次生成 |
| 首轮、历史、Topic Memory | 不产生额外标题、摘要、事实抽取或评审调用 |
| 生成前/释放前撤权或版本变化 | 阻断使用/释放，不能因 Fast 模式降低校验 |
| JSON 与 SSE | 执行相同检索、工具及生成步骤，生成预算一致 |

实施时还需分别测量解析/OCR、embedding、检索、来源复核、生成、输出校验耗时，
并与当前基线对比首字延迟、总延迟与答案质量。本次不预设尚未测量的速度或质量达标值。

## Thinking 执行顺序

定位：允许通过规划、工具观察和有限补查解决需要多步处理的问题，优先保证证据覆盖与答案完整性。
选择 Thinking 后即进入该链路；简单问题也不按关键词或复杂度规则转入 Fast。

```text
请求与当前身份校验 → 读取已核验的会话/Memory
  → 理解问题并按需改写、拆解与规划
  → 在当前授权工具和执行预算内选择下一步动作
      → 检索 / 读取原文 / 解析文件 / 处理图片
      → 校验工具结果并整理证据
      → 判断是否需要继续，必要时有限补查或调整计划
  → 证据足够或达到结束条件
  → Thinking 答案模型生成
  → 检查覆盖、引用和来源，必要时在剩余预算内修复
  → 最终来源复核 → 返回结果
```

### 规划与工具循环

- 可按需进行问题改写、子问题拆分和查询扩展；无需为每个简单问题强制执行全部准备步骤。
- 模型可以从服务端允许的工具中选择动作，并根据实际结果决定继续检索、读取原文或结束；工具返回失败时不能假设其已成功。
- TopK 证据不足时，模型可调用 `find_documents` 查看文档目录，再以 `get_document(doc_ids=[...])` 批量读取完整解析文本。目录只用于选择文档，不作为正文证据。
- 已删除规则式自动补检索及其规划器；证据校验不再自动扩大 TopK、切换 BM25 或发起第二轮搜索。
- 程序拥有工具白名单、来源范围、文件身份和预算的最终约束。模型不能选择其他 owner/KB、扩大附件范围或绕过原生权限。
- 请求明确包含的必需来源必须实际尝试并获得有效证据，不能由模型任意省略；缺少一个来源时不拿另一个来源代替。
- 可以扩展相邻块、读取更多原文、比较多个来源；每次读取必须保留其版本/hash 和来源依赖。
- 规划和答案生成均归属 Thinking 链路，最终答案固定使用配置的 Thinking 模型，不再由通用复杂度函数挑选 Fast 模型。
- 原文、文件和历史内容作为数据使用，不能自行增加工具权限或覆盖执行约束。
- 项目不提供独立视觉模型或视觉分析工具。Thinking 附件工具只消费文档解析、OCR 和表格证据；Fast 可将原图交给用户配置的多模态答案模型。
- 现有隔离中的 Wiki 导航不因 Thinking 允许工具循环而自动启用；Research 的企业来源限制也不因此改变。

### 预算与结束条件

Thinking 允许多次模型调用，但必须有统一的请求级预算，不能由各子模块自行无限追加调用。

| 预算项 | 约束 |
| --- | --- |
| 模型调用 | 规划、工具决策、最终生成和修复等生成请求全部计数 |
| 执行轮次 | 不能超过服务端配置及当前请求策略的上限 |
| 工具调用 | 检索、原文读取、文件处理、并行调用和补查都计入预算 |
| 检索与补查 | 允许有界重试和调整，不能因资料不足无限重复 |
| 时间和上下文 | 设置请求/工具超时、上下文及输出 token 上限 |
| 重复动作 | 无新证据的重复工具调用达到阈值后终止 |
| 质量修复 | 检查与修复消耗剩余总预算，不另开无限循环 |

- 证据足够时可以提前结束，不为凑满轮次继续调用工具或模型。
- 资料不足时可以在预算内补查；仍不足则说明缺失或返回不足状态，不生成无依据结论。
- 计划需要用户澄清时返回澄清，不先猜测扩大来源范围。
- 达到预算、工具/模型失败或质量校验不通过时，返回对应的明确结果；不自动改用 Fast，也不自动创建 Deep Research Job。
- 任何重试、补查、修复和最终释放都继续检查当前来源权限与版本。

### 质量与输出

- 证据覆盖检查、答案完整性检查和引用检查是不同职责，分别报告结果；引用编号正确不等于事实支持或问题覆盖完整。
- 修复只能依赖当前已授权且核验过的证据，结果必须重新检查；不通过的修复不能替换有效答案，也不能伪装为已通过验收。
- 本契约不新增外部评测/裁判 API。离线问题设计和答案评分继续遵守当前 Codex 逐案评审政策。
- JSON 和 SSE 驱动同一条 Thinking 业务流程；流式展示阶段、工具动作和允许释放的内容，不另写一套流式规划循环。
- 临时输出和最终答案沿用现有来源复核及持久化边界；来源失效时不能把已生成的文本当作新的可信来源。
- 两条链路共享响应和事件结构、身份、Memory、证据与引用能力，不共享会替用户重新选择执行模式的流程控制。

## Thinking 实施后的验收标准

以下是后续实现必须满足的断言，不是本次已执行的测试结果。

| 场景 | 必须验证 |
| --- | --- |
| 用户选择 Thinking 的简单问题 | 保持 Thinking 链路和 Thinking 答案模型，不调用 Fast |
| 多步问题 | 模型在允许工具内规划和行动，实际读取后再使用证据 |
| 首轮证据不足 | 可在剩余预算内补查，模型根据实际结果继续或结束 |
| 证据足够 | 可以提前生成最终答案，不强制耗尽循环预算 |
| 混合来源 | 全部必需来源均尝试，缺失来源不被替代，来源权限保持独立 |
| 工具越权或伪造文件身份 | 服务端拒绝，不能靠模型计划获得授权 |
| 重复调用或达到预算 | 可预测地终止；不进入 Fast 或自动创建 Research |
| 模型/工具失败及答案修复 | 如实记录结果，所有生成及工具调用都计数 |
| 图片理解 | 无独立视觉工具；附件 OCR 保留，Fast 原图随答案模型调用 |
| 生成、重试、修复及释放前撤权 | 阻断失效来源的使用与释放 |
| JSON 与 SSE | 共用同一流程、模型选择和请求预算 |

## 本次落地与剩余工作

| 项目 | 当前状态 |
| --- | --- |
| Fast 原问题检索 | 旧 `_retrieve_fast_context` 与 `FastLoop` 已移除，独立 FastPipeline 使用单次直接搜索 |
| Fast 生成预算 | 独立客户端只尝试一次，无回退模型、规划、生成修复或标题调用；BFF 跳过本轮后台 Memory 压缩 |
| 图片 | 同一答案请求携带授权原图；需配置支持图片的模型及 `FAST_MODEL_SUPPORTS_IMAGES=true` |
| 模式分派 | 显式选择；auto 兼容 Thinking，无复杂度选模型或隐式切线 |
| Thinking | 独立 ThinkingPipeline + 有界 Runner；固定 Thinking 答案模型，保留规划和质量检查，由模型选择目录及批量全文读取 |
| JSON / SSE | 同一业务流程，SSE 通过请求级事件桥交付；旧独立流式工具循环已删除 |
| 来源安全 | 保留模型前、释放前及 Reader 的当前权限、版本/hash 核验；增加原图文件 hash 绑定 |
| Thinking 统一预算 | 目前仍是各阶段与 Runner 的轮次/工具/补查限制，尚未形成覆盖规划、修复和辅助调用的统一总计数器 |
| 自动化验证 | Fast 单元、传输边界及 Chat 集成测试覆盖原问题、单次生成、引用拒绝、撤权/变版与 JSON/SSE；Thinking/auto 验证不进入 Fast |
| 真实验收 | 实际模型、检索、权限、图像质量及耗时对比待真实环境验收 |

既有历史验收报告和分数不据此改写。

### 本次验证记录

- 模式与来源安全专项覆盖 Fast、Thinking/auto 分派、JSON/SSE、图片打包、模型传输及来源撤权/变版。
- 前端 306 项测试通过，`vue-tsc` 通过；`pnpm build` 在 checkout 外的临时 SQLite 下通过。
- 模式拆分阶段 Agent 曾全量 970 项通过；其后并行迁移 `get_document(doc_ids=[...])`
  曾出现 3 项 Research 旧接口失败。该记录属于当时快照，当前验证须针对现有代码重跑。
- 规则式自动补检索移除后，Agent 全量回归 **966 项通过**；使用本次独立临时目录避免共享 SQLite 文件锁。
  覆盖空 TopK、低分和部分命中后由模型列目录/批量读取，以及证据不足时不自动增大 TopK 或切换检索方式。
- 这些是隔离模型/来源传输的自动化回归，未执行真实模型、图片理解质量或延迟验收。

### Thinking document exploration (2026-10-15)

Thinking can inspect TopK chunks and, when evidence is incomplete, browse the
metadata-only `find_documents` catalog (omit query to list; offset pagination),
then choose multiple IDs for `get_document(doc_ids=[...])`. The read tool returns
complete parsed content and source-bound citation chunks in one batch, without
hidden continuation or a chunk threshold. QA/comparison permit five tool calls
and five evidence retrievals within the configured Runner iteration limit;
metadata browsing consumes tool budget. Fast does not enter this loop.
Current per-document authorization and source dependencies are checked before
reads, before model calls and before release. Catalog metadata cannot satisfy
the factual evidence gate. Chapter-outline/scoped-search tools, their private service routes and the
unused private section-vector index are removed. Structured parsing and original
source locators remain.


## 2026-10-15 Failure handling clarification

- An explicit `{"claims":[]}` is an abstention (`no_relevant_context`), not a sourced answer or a validation failure. It does not save an assistant answer or create Memory effects.
- Reference IDs identify individual current excerpts. Quotes from another chunk, even with the same title/document, remain invalid for the selected ID. Fast supplies explicit IDs with each excerpt; the one-generation budget is unchanged.
- Thinking may end exploration after Groq rejects a tool call (`tool_use_failed`) only when accepted evidence already exists. It then makes one ordinary, tool-free final-answer call, retaining all binding, source-access/version and release checks. Failed provider tool text is never executed or recovered as an answer.
- Web maps Agent quality, model, retrieval/tool and execution-limit statuses to fixed public messages; timeouts have a separate status. Authentication, current-source/version and persistence failures retain the fail-closed access path. Raw provider errors, drafts and source bodies are not included in public failures.
# 2026-10-16 retrieval update

Fast still performs one original-query retrieval per selected source and one
answer generation. Search tools now use the common local English cross-encoder
to rerank a 20-candidate pool to the requested TopK (default 5). For mixed enterprise
and personal retrieval, Fast obtains up to 20 results from each source, builds a
bounded pool across sources and reranks globally to TopK. File/image attachment
context stays separate. Required-source checks still run after context selection;
reranking never grants access or changes source/version/hash lineage. Missing
local weights are logged as degraded ranking, not as successful semantic ranking.
Source candidates are revalidated before local reranker inference through a
request-local callback. Five primary hits can carry bounded original neighboring
chunks as separately identified context, without additional retrieval/model tool
planning. Citation Reader accepts noncontiguous table slices only by exact
current authoritative chunk identity/text after the existing live source checks.
