# integration/agent-demo-access-evidence 与本地版本对比

日期：2026-10-09。此次只获取远程对象并阅读代码/文档，没有切换分支、合并、迁移数据库、改动配置或启动评测。

## 1. 结论

建议通过 **fast-forward 合并**接入，不使用 reset/文件覆盖。先准备隔离配置和数据、记录当前恢复点，再合并并验证。该分支是本地最新提交的直接后继，不是需要丢弃本地功能才能采用的另一套实现。

| 项目 | 核对结果 |
| --- | --- |
| 本地分支 | agent-dev-infra |
| 本地已提交版本 | cdbe02b39793d0041f824e5409e93934f1810214 |
| 远程待比较分支 | integration/agent-demo-access-evidence |
| 远程版本 | 29f6c313dde52c806a0bdf833a60c4a4c19d9ce4 |
| 共同祖先 | 本地 HEAD cdbe02b |
| 两侧独有提交 | 本地 0；远程 3 |
| 文件差异 | 183 文件；6102 行增加，2342 行删除 |
| 已提交版本的合并关系 | 可快进，没有两个提交分叉导致的三方冲突 |

工作区还有聊天数据库、生成声明文件和无关未跟踪产物。两个已修改的已跟踪文件 `data-persistence/data/chat_history.db`、`frontend/components.d.ts` 在远程增量中均未变化。不过这些运行状态仍应独立保留，不能据提交关系承诺启动/构建绝不改动它们。

## 2. 三个新增提交

1. `1a9e91e`：原生来源访问控制和证据来源链。
2. `bfba784`：Web 回答及衍生状态绑定已验证证据。
3. `29f6c31`：隔离验收工具和交接说明。

## 3. 模块规模

| 模块 | 文件数 | 增加行 | 删除行 |
| --- | --- | --- | --- |
| Agent | 61 | 3486 | 195 |
| Frontend | 83 | 1739 | 2102 |
| Toolset | 7 | 124 | 5 |
| Attachment service | 5 | 107 | 5 |
| Data pipeline | 7 | 94 | 14 |
| Data persistence | 3 | 18 | 2 |
| docs | 12 | 378 | 18 |
| 根文件、Compose、脚本 | 5 | 156 | 1 |

增加行包含测试与文档，不是全部生产逻辑；Frontend 删除行主要来自重写/收敛路由和来源弹窗，不能仅按删除数量推断功能被移除。

## 4. 主要行为变化

### 来源权限与身份

新增 `SourceAccessProvider`、`AccessGuard`、`/api/access/*`。企业资料访问需要当前启用身份、本地 ACL、显式 Confluence 账号/站点绑定和原生 read 权限的交集。默认 SOURCE_ACCESS_MODE 为 native。权限不可核验时拒绝，不使用匿名身份或管理员绕过源站权限。

Research 路由新增 Bearer 依赖和明确 X-User-ID，取消 local-user 默认值。目录、Job 创建/读取、计划、批准、执行、进度、报告、下载和原文都纳入当前授权检查。

请求级 ContextVar 授权上下文传播到工具线程和模型请求边界，避免并行请求共享上次身份。

### Research 检索

`agent/app.py` 从 `from_local_catalog` 切到 `from_enterprise_catalog`，复用 Chat 的 search_documents/get_document Toolset。默认研究运行由本地 JSON 词法适配器转为共享企业检索/读取，联调资料使用 Milvus/BM25 hybrid。

LocalJsonSearchBackend 仍可用于固定 fixture，不等于整个生产检索被删除。Research 当前只支持企业 Confluence；个人库和附件支持范围是 Chat，不应扩展解释到 Research。Wiki 导航保留代码但因自身证据依赖不完整被运行时隔离。

报告生成增加 generation_method（model / verified_fallback），模型调用前后重新检查来源权限。既有 model_report.py 的大量质量处理保留，本次该文件仅少量增量。

### Web 回答与历史

回答附带 evidence.provenance.v1，关联全部读取/继承来源的版本、hash 与依赖。BFF 先缓冲生成结果，确认来源、保存成功并再检查后，才向浏览器释放最终正文。因此协议仍是 SSE，但不再意味着逐 token 即时显示未经核验正文；等待感和过程展示需要浏览器复测。

撤权或资料版本变化后，历史、收藏、复制/分支、Memory 和 Topic 摘要继续校验依赖。缺少来源链的旧记录可能被隔离，不自动回填为可信。这是与当前历史内容可见性有关的实质变化。

临时问答、独立保存、Topic 角色和会话上下文改为服务端权威，不能用浏览器上传的旧答案或角色信息绕过检查。

### 原文查看界面

新增消息绑定 Reader：`/api/messages/{messageId}/evidence/{evidenceRef}`。前端不再仅凭 doc_id 打开任意原文。

`ModalDocumentViewer.vue` 从约 411 行重写为约 112 行，展示回答时版本、hash、locator、实际摘录和已授权全文。旧版多 chunk 跳转条和整页分段高亮交互被替换为单条绑定证据及精确摘录定位；文案和视觉结构也发生变化。这部分不能称为保持原有样式完全不变。

Dashboard、Settings、Topics 页面、QuickNavDial、ReasoningFloatingWindow 本体在本次增量中未改动，既有主题与折叠实现仍保留。但调用路径/事件时序改变可能影响体验，不能只凭文件未变化判定完整 UI 已通过。

### 附件、入库和数据迁移

附件绑定 chat/topic、owner、有效版本和远端证据，过期时间单位明确为秒。私人向量查询维度与真实 embedding/collection 一致。

Confluence 导出/处理补充原生来源和有效状态元数据。旧资料是否具备所需字段及账号绑定，需逐项预检。

Web 新增 `0015_evidence_lineage.sql`，为 chats、topics、memory_snapshots、memory_facts 增加 evidence_provenance。消息来源证明保存在 parts。需要按完整迁移 journal 操作，并先备份数据库。

## 5. 已保留内容

Git 对比确认以下路径无远程差异：

- `docs/testing/repair_test_report_20261009.md`。
- Agent CP2 完整说明文档。
- `outputs/quality_repairs_qwen36_20261007/` 整个已提交证据包，包括日志、108 次运行和评分。
- 推理浮窗、右侧导航、Dashboard/Settings、Topics 页面主题修改。

历史说明会继续保留，但合并后“Research 默认本地词法”“Research 未统一校验 Bearer”等描述只能作为旧版本记录，新的用户指南应引用本分支 access-evidence 文档或增加新版说明。

## 6. 远程测试声明与质量边界

以下来自远程 `docs/pr63-integration-acceptance.md`，本次没有在本机复跑，也未取得它引用的外部机器原始产物，因此是远程报告声明：

| 项目 | 远程报告结果 |
| --- | --- |
| Agent 回归 | 849 passed |
| Pipeline/Storage/Toolset/Attachment | 326 passed，3 skipped |
| Frontend 回归 | 244 passed，45 files |
| 类型检查/构建 | 通过 |
| 最终来源/权限/Reader HTTP 检查 | 55/55 |
| 10 题 × G1/G2 单次 | 20/20 运行，19/20 机器质量 |
| G1 | 9/10 机器质量，平均 21.508 秒 |
| G2 | 10/10 机器质量，平均 49.119 秒 |

报告明确 PA-002 G1 漏掉 W34 功能/修复/其他改进字段，不能因为 4 条引用可定位就视为内容完整。人工质量评审仍 pending，完整浏览器点击和重复稳定性未完成。原 7 题属于回归，新增 3 题为生成前冻结的小留出集。

该组模型、数据、权限、检索后端和计时条件与本地 108 次验收不同，不能直接比较准确率/性能升降。远程额外验收产物位于另一台机器，本分支仅提交其索引和说明，不是所有原始日志均已上传。

## 7. 接入前条件与推荐顺序

1. 保存当前 `cdbe02b` 恢复点、备份 Web/Research 数据库，保留当前未提交文件。
2. 准备共享 WEB_SQLITE_PATH/TURSO_DATABASE_URL、内部 token、附件 secret、Confluence 原生权限凭据与明确用户账号绑定。保留当前模型配置，不能自动采用对方机器的模型/路径。
3. 检查文档来源元数据、企业和私人 collection、384 维 embedding 与 BM25/Milvus 一致性。
4. 使用独立空运行目录和 Compose 项目验证迁移到 0015；不用真实聊天数据库直接做撤权负例。
5. 以 fast-forward 合并指定 SHA 到当前分支。无需强行覆盖文件或制造 merge commit；本次尚未执行此步。
6. 执行 Agent/各模块/Frontend 回归与类型检查、构建。
7. 先检查登录、企业资料目录、权限与 Reader；再测英文数量/比较/未知回答、计划批准、报告与追问下载。
8. 重点复测 PA-002 类章节覆盖、旧历史可见性、撤权/恢复、修改资料版本、来源弹窗以及 SSE 等待/浮窗交互。
9. 修改旧 G1/G2 基准的接入：显式传可信用户和 Bearer，准备该用户合法资料范围；旧脚本缺 user_id/X-User-ID，不能预期原样运行。保留旧 108 结果，不覆盖历史统计。
10. 质量和交互通过后再考虑推送/更新 PR；不要把远程小样本报告直接当成本机全部验收完成。

## 8. 选择建议

**选择合并其增量，具体采用 fast-forward；不选择覆盖本地。**

理由：分支基于本地最新提交，历史代码与产物已经被继承；权限和来源一致性涉及多个模块，应完整接入，不能只挑 Agent 几个文件。快进不会丢失原提交历史，强制覆盖没有收益，反而增加运行数据和本地配置被误处理的风险。

但合并代码与切换现有运行环境应分开实施。当前严格权限配置、数据库迁移和 Reader/流式体验发生实质变化，先隔离验证，再让常用本地服务使用新流程。
