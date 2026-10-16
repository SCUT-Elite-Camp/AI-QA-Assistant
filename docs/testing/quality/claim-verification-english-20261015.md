# 断言核验全英文复测与测试默认语言

后续用户已选定仅保留 MiniCheck；当前实现与六条误判的输入对照分析见
[MiniCheck 分析](minicheck-error-analysis-20261015.md)。下文保留当时的完整对照数据。

2026-10-15，按用户要求，默认测试统一使用英文。
本轮结论以英文样本为准；[前一轮混合语言结果](claim-verification-offline-20261015.md)保留为历史记录。

## 英文结果

同一批真实英文原文，保留问题、来源、原文片段、字符位置、SHA 和预期事实关系；
63 条中文断言由 Codex 翻译并对照原文复核，另 63 条英文断言保持原样。
共 21 个问题、126 对英文断言/原文，三类 gold 各 42 条；未用外部模型翻译或评分。
冻结数据后才推断，不根据结果修改标签或阈值。

这些文档与原题已经被看过。本次是英文适配复测，不是新的未见 holdout。
前次真实聊天的三条中文回答没有被译后冒充新生成的英文回答；本轮未新增真实问答生成请求。

| 集合 | NLI 误放行 | NLI 误拒 | MiniCheck 误放行 | MiniCheck 误拒 |
| --- | --- | --- | --- | --- |
| 原开发题英文复测，84 条 | 0 / 56 | 3 / 28 | 1 / 56 | 2 / 28 |
| 原留出题英文复测，36 条，现已见 | 3 / 24 | 2 / 12 | 2 / 24 | 1 / 12 |
| 已知错误英文回归，6 条 | 0 / 4 | 0 / 2 | 0 / 4 | 0 / 2 |
| 总计，126 条 | 3 / 84（3.6%） | 5 / 42（11.9%） | 3 / 84（3.6%） | 3 / 42（7.1%） |

误放行以全部不受支持的断言为分母；误拒以全部有支持的断言为分母。
本次无超长或 needs_review 输入，不代表异常场景的完整验收。

两个模型都误放行了以下英文断言：

- `EN-Q16-3`: “The stated project-document update deadline is two days, not three days.”
  原文的项目文档更新期限是三天，两天属于另一行的纠正提醒期限。
- `EN-Q18-3`: “The Agent health endpoint proves retrieval resource readiness.”
  原文明确 health 只证明进程存活，ready 才报告资源就绪。

NLI 另误放行 `EN-Q17-4`，把 Web/Agent 必须共用权限库误读为可以互不相关。
MiniCheck 另误放行 `EN-Q11-3`，把只读 exporter 误读为重写页面正文。
NLI 误拒病例为 `EN-Q05-1`、`EN-Q10-2`、`EN-Q13-2`、`EN-Q19-1`、`EN-Q19-2`；
MiniCheck 为 `EN-Q10-1`、`EN-Q10-2`、`EN-Q16-2`。原文与逐条理由保留在外部私有数据中。

年份回归 `EN-Q21-5` 仍只给 July 30，断言加上 2023 年：两个模型都拒绝。
其中 NLI 的原生类别为 contradiction，gold 是 insufficient_evidence，说明三态类别仍会误判；
不能只凭“拒绝成功”宣称它正确区分了矛盾和缺少证据。

**结论：** MiniCheck 在本批英文数据上的误拒比上一轮混合语言数据少，
英文轮次不再支持沿用“因为中文误拒而优先 NLI”的选型理由。
本次两者误放行数相同，MiniCheck 误拒较少，NLI 推断更快；样本量和已见性质不足以批准在线拦截。
不再以混合语言结果替代英文场景结论。线上仍只做绑定/来源检查，没有新增语义门禁。

## 执行与耗时

模型修订、权重 SHA 和推断方法沿用前一轮的固定配置：
NLI `b5113eb38ab63efdd7f280f8c144ea8b13f978ce`，
MiniCheck `2f2d01a54fa022a7ffadb76260e1ea8bc88c82bb`。
CPU float32、4 线程、batch=4、argmax，模型顺序执行，没有调阈值或加关键词补丁。
最大 token 数 NLI 265、MiniCheck 216，没有截断。

| 指标 | NLI | MiniCheck |
| --- | --- | --- |
| 单条 forward p50 | 140.9 ms | 417.6 ms |
| 单条 forward p95 | 220.2 ms | 564.1 ms |
| 整个进程峰值工作集 | 1925.8 MiB | 1954.2 MiB |

同样取六个开发病例各两次、共 12 个单条测点；p95 是这组最大值。
不含权限/版本检查、tokenization、加载和完整回答，不能当生产 SLA。
翻译改变了 token 长度，不能把与上一轮的耗时差直接解释为系统提速。

每个 forward 前及最终释放前核对真实本地/native 授权及冻结源文件 SHA/原文位置。
本地 ACL 负例在有标记的 SQLite 副本执行并在 finally 恢复；两个最终探针均拒绝成功、恢复成功，
没有修改原数据库。不是检索、BFF、线上 native 撤权或完整生成验收。

```text
private/english-retest/cases.en.v1.json SHA-256
8f03ac6b631ff794d18b7c546e906e864108342311a9a8e8ce18dfe9885af3c1
```

原始数据、预先冻结的 `protocol.json`、逐条预测、summary、ACL 探针、加载诊断和日志位于：
`D:/AI-QA-Assistant/claim-verification-20261015/private/english-retest/`。
实际推断使用原离线 runner 的冻结版本，SHA 为
`ee0044d9796d373a1c99cd1e9be52ee467b5b776d68b8bbbf78b576ee9c85ed3`；
随后新增的默认英文输入限制另由单元测试验证，未重算或覆盖上述结果。

## 默认语言落地

- 根 `AGENTS.md`、[评测规则](evaluation-policy.md)、测试导航和两层 eval README：
  全系统默认问题、断言、普通资料、预期事实及生成答案/报告均用英文（`en-US`）。
  多语言、Unicode、编码或显式语言偏好专项可以保留目标语言，须明确其测试目的。
- Agent 的共用假模型回答、检索资料和标题改为英文；普通测试继承英文资料。
- 产品验收与 Research 默认 `product_acceptance.en.v2.json`；Research 缺省报告语言改为 `en-US`。
  原文来源范围和历史 manifest 不改写，历史数据与分数保留。
- 新整合 fixture 使用 `integration_holdout.en.v2.json` 的英文已见回归探针。
  Web/BFF 边界探针的普通资料和问题改为英文，模式由场景显式指定，避免翻译影响模式选择。
- Agent 本地 core/简单在线测试切换到 `.en.v2.json`，问题、历史对话和预期事实均为英文。
  保留原用例的历史契约性质，不据此宣称已移除的历史模块仍是当前产品实现。
- Deep Research suite 默认已有英文数据；会议记录探针的默认问题与回答指令改为英文。
- 断言 runner 默认要求输入声明英文原文和断言；`--allow-non-english` 只用于明确的语言专项。

这是测试配置与资料的默认语言，不强制改变产品用户的语言偏好或伪造历史验收结果。

## 代码验证

Agent 全量 `python -m pytest` 在英文共用资料改完后 **1009 项通过，40.91 秒**，
保留两项既有依赖弃用警告。使用独立外部 basetemp；日志为外部目录
`private/pytest-english-fixtures-full.log`。覆盖英文 profile 来源范围不变、Research 请求默认英文、
整合探针显式模式和非英文断言须显式开启语言专项等程序契约。

额外运行根 eval 指标、数据集、在线集合、延迟与历史 Research suite 的隔离回归：
**31 通过、2 未通过**，日志为 `private/pytest-english-root-v2.log`：

- `test_full_agent_bm25_request_does_not_call_vector_search` 未提供当前要求的 actor，
  被身份门禁以 `research_identity_required` 拒绝。没有放松身份检查去使旧测试通过。
- `test_assets_match_frozen_sources` 缺少历史 `data-pipeline/confluence_metadata_RAG.json`。
  没有补造历史元数据或改写历史 manifest。

因此不能宣称所有历史评测入口或整站均已验收。没有改动前端产品、在线权限或答案链路；
本轮没有运行前端构建/浏览器端到端验收。分类器质量结果与程序测试结果分别记录。
