# 集成分支合并后本地回归与抽测

日期：2026-10-09。当前本地 `agent-dev-infra` 已快进至 `29f6c313dde52c806a0bdf833a60c4a4c19d9ce4`，恢复分支为 `codex/pre-access-evidence-20261009`，指向 `cdbe02b`。本轮没有推送新分支状态，也没有覆盖原数据库或修改生产功能代码。

## 自动化验证

| 检查 | 本机结果 |
| --- | --- |
| Agent 全量 | 849 passed，3 warnings，26.85 秒 |
| Frontend 全量 | 45 files、244 passed，51.69 秒 |
| Toolset / Attachment / Pipeline / Persistence | 328 passed、1 skipped、3 warnings，51.49 秒 |
| Vue 类型检查 | 通过 |
| Vite/Nitro 生产构建 | 通过，输出到独立临时目录 |
| Web 0015 迁移 | 现有 Web 库的独立副本迁移成功 |

初次 Agent/前端测试遇到沙箱临时目录/子进程限制，提升本地测试执行权限后通过；多模块初次收集缺少 attachment-service 导入路径，补齐 PYTHONPATH 后通过。没有把这些环境失败当作产品测试通过，也没有修改测试断言来获得结果。

这些回归含 Mock/fixture，只证明其覆盖范围内的行为；真实模型结果另列。

## 独立服务与真实抽测

Agent 8109，Web 3019。Web 使用原 `frontend/.data/sqlite.db` 的独立备份；Research 使用新 SQLite 库。已有 3000/8010 服务未替换。独立内部 token 与会话 secret 只存在测试进程环境，不写入文档。

| 抽测 | 结果与边界 |
| --- | --- |
| Agent health / ready | HTTP 200、ready，retrieval/intent 已初始化 |
| Research 无认证目录请求 | HTTP 401 |
| 当前测试用户资料目录 | HTTP 200，39 份可访问资料 |
| 浏览器首页、Settings、Topics | 可打开；Topics 空状态显示正常 |
| 英文 W30/W34 比较题 | 提交、生成、引用和保存链路完成，但未检索到所需数量，正文返回资料不足；不能算数字准确性通过 |
| 消息绑定来源看板 | 读取成功，展示回答版本、hash、locator、摘录和原文 |
| 推理浮窗 | 可折叠，折叠后显示当前步骤 |
| 会话刷新 | 已保存问题、正文、引用恢复；本次刷新后浮窗重新展开，不据此宣称折叠状态跨刷新保存 |
| 英文 Fast 合同题 | HTTP 200/success、2 个引用；空证据、门槛、去重、过滤、引用来源、一次纠正与不足终态说明符合源合同 |
| Research 创建/规划/批准 | 201 创建，awaiting_approval；批准最新 version/hash 返回 200/ready |
| Research 执行/报告 | completed、complete、generation_method=model，4 个引用；正文为英文请求流程与证据要求 |
| Web Research 会话注册/消息保存 | 均 HTTP 200，使用真实后端正文和来源绑定 |
| Markdown 下载 | HTTP 200，text/markdown，下载文本与报告逐字一致 |

真实抽测使用当前配置模型和既有本地索引，不是重跑此前冻结的 108 个坐标。当前资料/ACL/索引范围与历史评测不同，因此不能将 W30/W34 的未回答直接判为同条件下质量回归，也不能据两条链路成功宣称全部内容能力不变。

## 原生 Confluence 权限待验证

当前私有配置缺少 Confluence token 和确认后的账号绑定。用户提供的站点/邮箱已写入忽略的 `.source-access.env.local`，token 留空，bindings 未自动赋权。

本机现有部分资料按当前元数据被识别为本地文档，可以在本地 ACL 内读取；本轮真实模型成功不代表已经验证 Confluence 原生 read 权限。必须补齐凭据、确认账号和资料来源元数据，再验证授权、拒绝、撤权/恢复及研究生命周期。

没有启用 approved_snapshot 绕过原生检查，没有把一个来源账号绑定给全部用户，没有上传私有配置。

## 产物

- Agent 日志：`D:/htc_qa/.tmp/merge-agent-tests-elevated.log`
- Frontend 日志：`D:/htc_qa/.tmp/merge-frontend-tests.log`
- 类型检查：`D:/htc_qa/.tmp/merge-frontend-typecheck.log`
- 模块回归：`D:/htc_qa/.tmp/merge-module-tests-path.log`
- 构建日志：`D:/htc_qa/.tmp/merge-web-build.log`
- 独立数据库与真实抽测结果：`C:/Users/Fiona/.codex/visualizations/2026/10/02/01a0fba1-4ffc-72c3-a36f-1e66fec96f42/merge-smoke-20261009/`

以上是本地产物，不自动随源码推送。该目录含独立数据库和服务日志，后续交付应选择脱敏证据，不整体上传。

结论：合并无冲突，本机回归与主要抽测链路可用；Confluence 原生授权和原冻结数字问答的同条件复测尚未完成。

## 配置后原生权限续测

使用用户指定的 data-pipeline/.confluence.env，未复制或输出 token。CONFLUENCE_BASE 原值含 /wiki，账号查询按站点 origin 正确构造路径。账号接口 HTTP 200，已确认 native account_id，并仅对独立测试 dev-user 建立绑定。

W30/W34 Agent 页面实际原生 read 检查通过；两个页面的消息来源接口均 HTTP 200 并返回正文。未知本地 actor 的资料访问返回 403。仅这两个来源的正例和未知身份负例通过，不代表全角色/撤权/版本漂移矩阵完成。

数量题 G1 在线调用遇到模型 insufficient_quota，未取得有效答案；G2 创建、规划与批准已执行，内容质量不计通过。尝试取消运行中 G2 返回 409：当前 cancel 契约不支持 researching 状态。保留该结果，不将按钮存在当作执行中可取消。后续仅接续未完成数量用例，不重跑已完成回归和合同题。


## 2026-10-09 原生数量题续测结果

当前模型 `qwen3-30b-a3b`。只接续未完成 W30/W34 数量题，未重跑已完成回归、合同题或历史冻结坐标。文档/BM25 数据副本、Web DB、Research DB/checkpoint 和 topics 位于 checkout 外的独立测试目录；既有 Milvus 索引用于读取，未替换原集合。

| 维度 | G1 | G2 |
| --- | --- | --- |
| 运行 | HTTP 200 / success | completed / complete / generation_method=model |
| 数字核对 | 8 个源数值与 4 个差值全部正确 | 8 个源数值与 4 个差值全部正确 |
| 耗时 | 22.28 秒 | 前端执行记录 333.8 秒；客户端轮询 340.64 秒 |
| 引用 | 4 个有效证据，末尾另有无效 `[n]` | 5 个引用；变化量表仅标 W30 的 `[2]`，缺少同行 W34 支持 |
| 内容问题 | 末尾额外泛化句无证据支持 | 声称具体改动和 W30 other improvements 未说明，与原文提交明细矛盾 |
| 人工内容结论 | 数字子项通过，整体质量不通过 | 数字子项通过，整体质量不通过 |

期望值顺序为 commits/features/bug fixes/other improvements：W30=9/5/1/3，W34=8/3/5/0，W34-W30=-1/-2/+4/-3。核对依据是实际资料的指标段和提交明细，不是另一模型评分。此处 12/12 仅是本题数字检查，不能作为测试集总体准确率。

前端可恢复会话、显示研究进度和最终英文表格/来源/执行记录，完成状态 3/3 任务、9 条证据。服务重启使旧浏览器 session 失效，首页开发登录恢复后正常。G2 执行期间有 Confluence 连接池告警，耗时原因尚未完成剖析；未降低原生权限校验以改善速度。

本次产物：独立目录下 qwen30-native-g1.json、qwen30-native-g1-review.json、qwen30-native-research-created/plan/latest/report/review.json、qwen30-native-report.md，以及 agent/web-qwen30 日志。未修改历史分数，未自动推送原始资料或数据库。

结论：原生授权的数量问答与研究运行链路已跑通；无效引用、对比引用覆盖、错误限制说明与研究性能仍需处理，不能宣称合并后质量全部验收通过。

补充前端复测：实际点击下载成功，下载文本与后端 markdown 逐字一致。点击 W34 引用按钮两次均未显示原文面板；该交互暂记未通过/待定位，不能据之前合同题 Reader 成功代替此项。


## 缺陷修复与针对性复测

1. G1 格式器丢弃携带字面 `[n]` 占位引用的无依据句子，保留正常数组索引 `array[n]`；完整性检查不再把导入正文粘连词 theAgent 当作必答代码符号，用户明确提问该标识符时仍保留检查。
2. 数量报告从每份文档标题/标题片段解析周次，不依赖引用排序。每个周次值引用本周证据，差值同时引用两周证据；完整指标表不追加泛化限制段。
3. Research 工具在已冻结来源范围内实时检查权限，显式范围创建也只检查所选文档；没有权限缓存，没有移除撤权或版本/hash 校验。
4. 正文引用使用页内原文看板，通过原 Research 来源 BFF endpoint 校验，展示原文、摘录、版本、hash 和片段跳转。前端实测成功，不再打开裸文本接口标签页。

验证：Agent 全量 851 项通过；随后新增的范围撤权和粘连词回归所在 19 项针对性测试全部通过。前端 244 项通过，vue-tsc 类型检查与生产构建通过。UI 机械检查无发现。截图位于本地 `.tmp/research-source-repaired.png`，未上传资料截图。

最终 G1 实际模型复测 success，耗时 17.08 秒，12/12 数字与差值正确，引用有效，没有多余无引用补充句。G2 实际规划/检索/原生权限链路 completed，客户端总耗时 38.36 秒（前端执行记录 22.3 秒），12/12 数字与差值正确、双来源差值引用正确、没有错误限制说明。G2 此类完整一致指标表走来源驱动的确定性报告生成，generation_method=deterministic；不能将其称为模型撰写质量通过。此前同题客户端约 340.64 秒，此次 38.36 秒；仅是单次同题观察，不是总体性能或重复稳定性结论。

本次是 repair-informed 缺陷用例，不是未见 holdout。未重跑历史冻结集，未修改历史成绩，未实测全角色/撤权/版本漂移完整矩阵。本次修复与针对性回归说明随 agent-dev-infra 分支交付；私有配置、运行数据库和原始来源资料不在提交范围内。
