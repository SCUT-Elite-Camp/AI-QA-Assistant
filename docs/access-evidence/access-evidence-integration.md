# Web / Agent / Toolset 接入契约

2026-10-16 检索默认使用本地英文 Cross-Encoder，把 20 个候选重排到 TopK（默认 5）。
重排输入先验证当前权限、来源版本/hash 与原文；权威 chunk 未匹配的旧向量文本不进入模型。
原 score 保留用于既有阈值，rerank_score 单独表示相关性。主命中可附带有独立标识/hash
的原始相邻 chunk，仍经过模型调用前与释放前的来源复核。Reader 对带重复表头等非连续
表格片段，在原有实时权限与整篇版本/hash 校验后，要求当前服务端 source.chunks 中存在
唯一、相同 chunk_id 且文本精确一致的片段；不通过关键词、标题或浏览器提供的片段放行。

2026-10-15 历史浏览策略（用户明确指定）：`GET /api/chats`、`/api/chats/:id`、`/api/chats/favorites`、`/api/topics`、`/api/topics/:id` 及其 documents/dialogues GET 接口只读持久化快照，不调用来源校验服务。继续验证启用用户、私有聊天归属和当前 Topic 成员；来源服务不可用、版本改变或撤权不阻断这些历史快照。主题文档 GET 返回数据库保存的标题/摘要，不承诺为源站当前内容。再次生成答案、Memory 复用、原文 Reader 和 Research 任务接口仍走实时来源校验。本段覆盖下文对应普通浏览路径的旧规则，不提供缓存授权。

2026-10-15 已移除独立视觉模型：不再加载本地 VLM，不提供 `inspect_attachment`
及私有 inspect 接口，也不运行视觉推理子进程。上传图片的文字/表格 OCR 继续由 Pipeline
处理；Fast 原图仍随用户配置的多模态答案请求一次发送。旧数据库 `vision_status`
字段仅作兼容保留，不再运行视觉状态机。

2026-10-15 文档工具收敛：Thinking 在 TopK 证据不足时可用 `find_documents`
列当前可访问的文档目录（可不传 query，offset 分页），再选择文档调用
`get_document(doc_ids=[...])` 一次读取最多 20 篇完整解析文本与引用块。
目录不转换为引用证据；章节浏览和章节内再检索工具、对应私有后端接口及
专用章节向量索引已移除，结构化解析和原文定位继续保留。批量读取前逐篇鉴权，
目录与正文均保留全部来源的当前权限/版本/hash 依赖，回答前继续证据校验。
Fast 不进入此补读循环。

2026-10-15 模式拆分：Fast 和 Thinking 分别由 `agent/chat/fast.py`、
`agent/chat/thinking.py` 执行。Fast 原问题单次直接检索、程序固定调用工具、一次生成，
不规划、不扩展、不生成修复、不追加标题或本轮 Memory 压缩；HTTP 也只尝试一次。
`auto` 已兼容到 Thinking，不再根据复杂度切线。JSON/SSE 共用各自业务流程。
Thinking 保留原有有界规划/工具能力及固定答案模型，统一总调用预算仍待实现。
完整当前契约见 [Fast / Thinking](../../agent/docs/chat_mode_contract.md)。

Fast 图片工具读取已有解析/OCR和授权原图，排除独立视觉模型结果。原图随最终答案请求
一起发送，要求多模态 `ANSWER_FAST_MODEL` 及 `FAST_MODEL_SUPPORTS_IMAGES=true`（默认 false）。
`FAST_CONTEXT_MAX_CHARS` 默认 12000。图片引用/依赖新增 `content_kind=file`，
绑定当前文件 SHA-256 与 evidence version；普通片段默认 `excerpt`。Reader 的文件 URL
携 `expected_hash`/`expected_version`，BFF 与私有文件接口继续复核，旧/未知 lineage 不补信任。

以下早期整合记录保留历史背景；其中 Fast 的多查询、补充读取、生成修复及重试描述已由
上述 2026-10-15 契约替代，历史分数不代表本次真实验收。

Groq GPT-OSS 配置：Fast 使用 `openai/gpt-oss-20b`、`reasoning_effort=low`，
Thinking 使用 `openai/gpt-oss-120b`、`reasoning_effort=high`。
共享客户端将模式转换为 Groq 参数并使用 `max_completion_tokens`，不发送
`enable_thinking`/`thinking_budget`，失败不切换到其他供应商模型。
查询规划使用配置的 `QUERY_PREPARATION_MODEL`；Fast 的特殊答案校验跟随 Fast 模型。
实际密钥只存放于忽略的环境文件；权限及来源复核边界保持适用。

2026-10-13：保存引用 Reader 复用 `locateEvidenceExcerpt`，兼容反引号和下划线转义等
Markdown 表示差异，避免合法引用打不开；消息归属、当前权限、版本、正文 hash
与释放前复核保持不变，实质正文变化仍拒绝读取。

2026-10-14：Reader 同时匹配表格 Markdown 的 HTML `<br>` 与解析器引用中的换行，
映射回原文位置；保留数字、列顺序及代码中的字面标签校验。完整 Fast 基线先保留
原始两条表格 Reader 409，修复后仅重读已保存引用，单列复测结果。

Fast 企业问答现在先缓冲模型正文，校验引用后再释放 `token`。事实回答必须有
有效的数字引用；全角及组合编号会规范化，未使用引用会移除并重编号，来源的
`evidence_ref` 保留。缺少引用时最多使用同一 Fast 模型及已授权证据修复一次；
仍不通过则 `done.status=QUALITY_VALIDATION_FAILED`，不释放该正文。
因此 Fast 的首个正文 token 延迟包含生成及校验时间。编号校验不能替代事实支持
或答案完整性评测。纯知识库关闭的直接回答沿用原有流式路径。

Fast 保留原问题及最多三个规划子查询，候选数为 10–20；读取前三个命中文档
的相邻片段，短文档最多读取 12 个片段。模型上下文最多 30 条证据、4000 字符
展示正文；表格引用保持原文连续片段，列对应语义来自同一份当前授权原表。

更新：2026-10-12。架构见[访问边界与证据链路](access-evidence-architecture.md)。

Deep Research 默认使用当前用户可访问的全部企业 Confluence 文档，网页不再要求选源。
`source_scope.all_documents=true`（省略/空范围同义）由认证服务端转换为显式授权文档列表；
后续 Plan/Manifest/Approval 仍绑定版本/hash，并继续逐次复核原生权限。
Research 提示、计划说明、状态事件、操作确认及引用 Reader 统一为英文；回答正文遵循请求语言。

附件服务按当前产品要求仅负责文件格式/大小校验、解析与上下文返回；病毒扫描功能已移除，开发和生产均不依赖 Defender/ClamAV。`ATTACHMENT_SCANNER`、`ALLOW_FAKE_ATTACHMENT_SCANNER` 和 readiness 的 `scanner_ready` 字段已删除。`/health/ready` 检查服务自身运行状态；新上传直接进入 `parsing`。既有附件身份、Chat/Topic 绑定、有效期与证据版本校验仍适用。

2026-10-15：附件上传和存储 API 改由 Agent 托管。内部基址统一为
`AGENT_BASE_URL/private-files`，原 `/v1/**` 路径及 `ATTACHMENT_INTERNAL_SECRET` 验证保留；
`ATTACHMENT_SERVICE_URL` 不再使用。浏览器仍通过原同源 BFF 路由。
Toolset 的 `parse_attachment_context` 调用 Pipeline 解析、返回字符串 `context` 和 `items`，
Data Persistence 保存包含结构化 `documents` 的快照。个人库后续使用该快照切块与索引。
对话上传由 BFF 注入 `X-Library-KB-ID/Document-ID/Version-ID`（三项必须同时存在），
建立独立私有版本，并返回 `document_id/version_id`；身份和 KB 由服务端会话分配。
解析只执行一次，后续队列复用快照；临时附件删除/过期不删除个人库副本。
Web 后台同步 READY 并执行原活动版本 CAS，不依赖用户打开资料库页面。
Research 的企业来源限制保持有效。
Python 内部工具与 AccessGuard 直接调用 Pipeline/当前存储，避免同步 HTTP 回调同一 Agent
进程造成阻塞。ContextVar allowlist、个人库 HMAC 上下文以及每次使用前的当前版本/权限
校验继续执行；只共享存储/模型句柄，不缓存正向授权。

## 浏览器接口

浏览器只请求同源 Web API。用户来自服务端会话；写请求携带 `useCsrf()` 提供的 header。不要把 Agent Bearer、内部 token、Confluence token 或附件 HMAC 放进 `VITE_*` 配置。

| 接口 | 用途/约束 |
| --- | --- |
| `GET /api/documents`、`GET /api/documents/{docId}` | 当前身份可访问的企业目录/原文，非公开 JSON 文件服务 |
| `POST /api/chats`、`POST /api/chats/{id}` | 服务端创建 Chat；只接收最后一条 user 提问，历史与内部上下文从数据库读取 |
| `GET /api/chats/{id}`、`GET /api/chats/favorites` | 当前角色与来源依赖双重过滤，撤权后不释放旧正文 |
| `GET /api/messages/{id}/evidence/{ref}` | 消息绑定原文 Reader；路径片段必须 `encodeURIComponent`，包括 `:assistant` 和 evidence ref |
| `POST /api/chats/temp-ask` | 临时问答仍创建服务端拥有的会话；返回 `data-temp-chat` 中的真实 chat ID |
| `POST /api/chats/save-standalone` | 提交 `sourceChatId` 和已保存消息 ID；读取服务端原记录，不保存客户端伪造答案 |
| `/api/research/jobs/**` | 同源 Research 代理；GET 当前 ACL，所有写操作检查会话/CSRF |
| `GET /api/research/documents`、`GET /api/research/download?researchId=...` | 授权目录与报告下载；下载响应 private/no-store |
| `POST /api/research/chats`、`POST /api/research/messages` | 保存真实服务端报告与其证据绑定，不信任浏览器报告正文 |

Topic viewer 只读，editor/owner 才能发消息。当前成员关系优先于历史创建者字段；移除成员后不能通过旧 Chat 或附件继续访问。

## 服务端接口

以下访问接口实际前缀为 `/api/access`，要求 Bearer + 可信 `X-User-ID`，响应 `Cache-Control: no-store`：

| 接口 | 输入/输出 |
| --- | --- |
| `POST /api/access/check` | `{doc_ids:[...]}` → `{allowed_doc_ids:[...], denied_doc_ids:[...]}`；最多 200 项 |
| `GET /api/access/documents` | `{documents:[...]}`，包含版本与正文哈希，读取后再次检查目录授权 |
| `GET /api/access/documents/{id}/source` | 可传 `expected_version`、`expected_hash`；版本不符 409，拒绝/缺失 404 |
| `POST /api/internal/chat/retrieval/stream` | Bearer + `X-Agent-Internal-Token`；`InternalChatRequest` 包含 BFF 构造的 Memory、个人库及附件上下文 |

示例（仅在可信后端/测试终端运行）：

```powershell
$headers = @{Authorization="Bearer $env:AGENT_API_KEY"; 'X-User-ID'='accept-alice'}
Invoke-RestMethod "$env:AGENT_BASE_URL/api/access/check" -Method Post -Headers $headers `
  -ContentType application/json -Body '{"doc_ids":["<authorized-doc-id>"]}'
```

Public Chat 需要 Bearer 与显式用户，不接收浏览器提供的 Memory、个人库、附件授权上下文。Public API 不直接暴露在浏览器网络中。

身份字段不要混淆：Public Chat 从受 Bearer 保护的请求体 `user_id` 读取；access 与
Research 使用可信 `X-User-ID`；内部 Chat 同时检查请求体身份和 BFF Memory actor。
这些都是服务端委托接口，不是允许浏览器自行填写 user ID 的登录方式。

## Evidence 协议

```json
{
  "schema_version": "evidence.provenance.v1",
  "complete": true,
  "dependencies": [
    {"source_type":"knowledge","doc_id":"example-doc","version":"1","content_hash":"<body-sha256>"}
  ]
}
```

`dependencies` 支持 `knowledge`、`personal`、`attachment`。个人库还必须绑定 `knowledge_base_id`、`document_id`、`version_id`；附件必须有有效 evidence version/hash。Pydantic 空 optional 字段的 wire 值可能为 `null`，Web 会正规化为空；这不免除各来源必填字段的校验。

SSE 的 `done.evidence_provenance` 与输出 Citations 必须匹配，且全部来源仍有效。
Chat 模型通过真实流式调用产生片段；Agent 每次释放片段前重新校验权限和版本/hash，并发送 `source.evidence_provenance`。
BFF 在该边界重新校验当前身份与来源，才通过临时 `data-answer-preview` 显示后续模型片段；未携带完整证明的旧流保持缓冲。
最终质量修复可通过 `answer` 替换草稿，完成后经过校验、落库与再次来源检查才发布完成的消息。
失败、取消及不足证据不保存草稿；校验失败会清除网页草稿。来源型历史/Memory/引用 Reader 仍只使用已保存的最终消息。
`data-answer-status={status:no_relevant_context,persisted:false}` 只表示未保存的不足证据提示。

Memory 的 Snapshot/Fact/Tail、Topic 摘要须传递相同 lineage；不能用 `complete=true, dependencies=[]` 给已有知识回答洗白。纯用户偏好等不依赖资料的内容可以合法为空依赖。
Chat 属于 Topic 时，Web 先校验当前成员身份与 Topic 摘要的完整来源，再把 `soul_content` 和来源依赖传给 Agent；Agent 在模型调用和回答释放前重查这些依赖。旧版或已撤权的摘要不进入模型上下文。Topic 文档池的 `is_user_uploaded` 列由迁移 0017 添加，运行时 schema reconcile 也会补齐旧库。

## 失败语义

| 状态 | 含义与调用方行为 |
| --- | --- |
| 401 | 没有有效会话或 Agent Bearer；重新认证，不能退回匿名用户 |
| 403 | 当前用户被禁用/角色不足/明确拒绝；不能换用 admin 或源站服务账号 |
| 404 | 不属于该用户或不可访问的资源；不泄露存在性 |
| 409 | 版本/哈希/活动指针改变、批准过期或缺已保存证据绑定；重新读取/研究 |
| 503 | 权限来源/内部凭据/安全导航依赖不可核验；修复依赖，不允许无过滤兜底 |

Chat 中途失败只能产生安全状态提示，不能保存成成功回答。接口状态、来源合法性、引用事实支持和回答覆盖是四个不同验收项目。


### Research inline source Reader (2026-10-09)

Report citation buttons open the existing themed Reader in-page. Research reads use the session-owned BFF `/api/research/jobs/{research_id}/documents/{doc_id}/source` endpoint; frozen job membership, current ACL/native permissions and source version/hash are checked server-side on each read. The UI displays the selected report excerpt/version/hash and the authorized full text; it does not substitute an unrestricted document endpoint or browser authorization context.

Research Evidence and Citation may include `anchor_excerpt`: the text of the exact locator block, independently of the surrounding `excerpt` context. Reader highlights this anchor while still displaying the surrounding context; matching can ignore Markdown code delimiters and whitespace, while preserving substantive tokens and original-body offsets. Precise commit/source locator answers must find the requested fact in this anchor, rather than infer its location from neighboring blocks. Older records without this optional field retain their existing excerpt semantics; they are not backfilled as new verified anchors. Small documents (at most 12 chunks and 6000 body characters) can supply bounded complete context, while the anchor remains the exact original chunk. Every read still checks current native permissions and frozen version/hash.

For G1 factual/comparison requests, including selected scope comparisons, recorded status tables and capability summaries, with at most four explicitly selected documents, the policy allows bounded original reads through the existing guarded ToolExecutor. This expands evidence coverage, not authorization. Calendar comparisons use the document's recorded meeting/report date when unambiguous; the source version/export timestamp remains provenance and is not rewritten to that event date.

For evidence-insufficient entity/count answers, citations support quoted headings from the inspected sources. A missing requested number is expressed as a scope limitation, without pretending an unrelated source positively proves that absent value.
## Adaptive composer (2026-10-13)

Home and chat retain their original capsule for one line. Explicit newlines or text wider than the compact input area move the text above the controls; shortening the text restores the capsule. The compact width calculation remains stable while expanded and observes control and container resizing. A Deep Research badge alone does not expand the composer. Attachments retain their existing expanded tray. Input and request behavior are unchanged. Selection actions anchor the pill's top-left corner 2 pixels right and 2 pixels below the last selected line's bottom-right corner, clamped within the viewport; composer buttons retain their original arrangement.

## Selection conversation UI (2026-10-12)

Selection Q&A uses a separate server-owned temporary conversation. The transport
reuses `tempChatId` for follow-up questions. Successful `data-temp-chat` events
carry `{chatId, messageIds}` containing the persisted user/assistant IDs; Save
sends those IDs with `sourceChatId` to `save-standalone`. Failed requests and
browser-supplied message contents are excluded from the saved copy. The BFF
continues to check ownership and current source lineage before copying messages.

The current JSON selection endpoint requires the Agent's
`PERSISTENT_MEMORY_ENABLED=true`. Its coordinator and confirmed-Fact recall
policy share the same request visibility cutoff. Session Facts remain governed
by their separate feature flag. Selection answers are currently delivered after
the final source checks.

The drawer uses a multiline composer (Enter sends; Shift+Enter adds a line), a
compact expandable quote, and a single short empty-state prompt. Below the desktop
breakpoint it fills the chat panel, preserving the visible composer and close
button. Quick navigation is hidden while this drawer is open.
The selection toolbar appears below the selected text and stays within the
viewport, avoiding the browser's native selection menu above the selection.

## Main chat streaming presentation (2026-10-12)

Transient `data-answer-preview` events carry the server-generated `messageId`.
`phase: 'start'` opens an empty preview, `delta` queues checked provider text,
and `phase: 'complete', text` replaces the queue with the verified final answer.
The completion event is emitted after durable persistence and the existing
current source checks, before the canonical SDK text. A plain `reset: true`
clears previews on failure or insufficient evidence. These transient events
are not persisted as chat messages.

The frontend reveals buffered text on animation frames using Unicode graphemes,
with an adaptive rate and at most four graphemes per frame. It keeps the preview
until both presentation and the canonical message finish, avoiding a sudden
final-answer jump. A repaired final answer removes the differing draft suffix
and discards old queued text. Stop, failure and unmount cancel pending paints;
Stop after verified persistence reveals the remaining saved answer immediately.
Reduced-motion preferences and hidden tabs use instant presentation. Existing
history renders immediately; persisted text and citation/permission checks are
unchanged. The main chat's Fast, Auto and Thinking modes share this presentation.

Recently revealed prose also gains contrast over a 420 ms opacity animation.
Animation birth times belong to each Markdown renderer, so reparsing does not
restart a character's fade. Only up to 96 recent graphemes have wrappers; older
text, citation widgets and highlighted code retain their normal rendering.
The effect inherits the current theme's text color, does not move or blur text,
and is disabled by `prefers-reduced-motion`. Historical messages do not animate
on load.
