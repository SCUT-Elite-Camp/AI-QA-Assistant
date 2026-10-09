# Web / Agent / Toolset 接入契约

更新：2026-10-09。架构见[访问边界与证据链路](access-evidence-architecture.md)。

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

SSE 的 `done.evidence_provenance` 与输出 Citations 必须匹配，且全部来源仍有效。普通 BFF 会缓冲 Agent 流，校验和落库后才释放最终回答；因此使用 SSE 不代表逐 token 未校验输出。`data-answer-status={status:no_relevant_context,persisted:false}` 只表示未保存的不足证据提示。

Memory 的 Snapshot/Fact/Tail、Topic 摘要须传递相同 lineage；不能用 `complete=true, dependencies=[]` 给已有知识回答洗白。纯用户偏好等不依赖资料的内容可以合法为空依赖。

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
