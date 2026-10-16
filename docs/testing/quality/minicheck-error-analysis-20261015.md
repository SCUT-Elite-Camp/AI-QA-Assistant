# MiniCheck 选型与六条误判分析

2026-10-15。用户决定保留 `lytang/MiniCheck-DeBERTa-v3-Large`，移除其他核验模型。
本报告承接[全英文复测](claim-verification-english-20261015.md)。

## 实施结果

`agent/eval/claim_verification_acceptance.py` 现在只支持 MiniCheck：删除其他模型仓库、
输入分支、三态预测映射和 `--candidate` 参数，不保留兼容别名或回退。
当前仍是离线核验入口；选型本身没有改变 Fast/Thinking 的在线链路。

本地 NLI 权重 `model.safetensors`（557,652,046 字节）已删除，
`D:/AI-QA-Assistant/claim-verification-20261015/models/mnli/` 已从活动模型目录移除。
递归/批量清理命令被执行层拒绝后，采用范围更小的单权重文件删除完成授权操作；
剩余非权重元数据移入 `private/historical-nli-metadata/`，历史对照结果与冻结记录保留。
MiniCheck 原权重未改动，固定修订仍为 `2f2d01a54fa022a7ffadb76260e1ea8bc88c82bb`。

单模型入口重跑原 126 对英文样本，与原 MiniCheck 的 **126 个标签完全一致**：
误放行 3/84，误拒 3/42。4 个问题中共有 6 条误判断言；不是 6 个不同的问题。
数据与标签未修改，这些已见复测不能当作新 holdout。

## 误放行：错误断言被判为有支持

### EN-Q11-3：把只读导出理解成改写源页面

**Question:** How does the enterprise pipeline export and retract source content?

**Claim:** The exporter rewrites Confluence page bodies.

**Source:** Data Pipeline，片段开头是：

> The enterprise path uses a read-only Confluence exporter to capture current body, metadata, and structure.

同段后文描述 pipeline 的写入索引、重建 BM25、更新本地 JSON projection。
这些是派生存储操作，不是 exporter 改写 Confluence 源正文。
人工标签为 contradicted，MiniCheck 原样重跑仍预测 supported。

**输入对照：** 保持错误 claim 不变，只提供上述含 read-only 的原文句子，判定转为 not_supported。
在原整段上下文中，把 claim 写成
“The read-only Confluence exporter modifies the original Confluence page bodies.”，也转为 not_supported。

**分析：** 结果支持“长段中不同主体/写入对象混淆、只读限定未稳定保留”的解释。
原段同时包含 exporter、pipeline 与写入操作；聚焦相关句后能正确拒绝。
这不能证明模型内部究竟关注了哪些 token，但说明正确的限制已在输入中，不是原文缺失或截断。

### EN-Q16-3：把纠正期限挪给项目文档更新期限

**Question:** What are the stated maintenance deadlines and bot schedule?

**Claim:** The stated project-document update deadline is two days, not three days.

**Source:** User Guide 表格分别规定：

- Upload deadline 行：update project documents within **3 days** of any change。
- Correction reminders 行：Please make corrections within **2 days**。

人工标签为 contradicted，MiniCheck 原样重跑仍预测 supported。
错误数字确实出现在同一张表，但属于另一个业务要求。

**输入对照：** 保留表头与正确的 Upload deadline 行，去掉其他行后，原 claim 转为 not_supported。
只把完整表格线性化成“行名：内容”，保留全部行，仍预测 supported。
同一整表上，正确的三天更新期限断言能被接受。

**分析：** 主要证据指向跨行关系绑定失败。仅去掉 Markdown 表格分隔符没有解决问题，
不能简单归因于“模型不认识表格符号”。它需要稳定匹配“哪项要求—哪个期限”。

### EN-Q18-3：把 health 与 ready 的职责混在一起

**Question:** What do health/readiness endpoints and isolated ports mean?

**Claim:** The Agent health endpoint proves retrieval resource readiness.

**Source:** Deployment Architecture 明确写道：

> Agent `/health` proves process liveness only; `/ready` reports retrieval and other resource readiness.

人工标签为 contradicted，MiniCheck 原样重跑仍预测 supported。

**输入对照：** 只保留上述对比句，原 claim 转为 not_supported。
保留整段，仅把 claim 改成更明确的
“The /health endpoint proves that retrieval resources are ready.”，仍然误放行。
同段上，正确的 “The /health endpoint proves process liveness only.” 也预测 supported。

**分析：** 模型能接受正确陈述，却没有在整段上下文中稳定排除相反陈述。
端点与职责的对应、only 限定及分号两侧的对比关系没有被可靠保留。
仅让断言显式写出 `/health` 不足以修复，缩小到相关对比句才改善。

## 误拒：有原文支持的断言被判为不支持

### EN-Q10-1：否定排他关系的等义转述失败

**Question:** Which dependencies and Reader checks are retained?

**Claim:** Provenance contains read and inherited dependencies, including ones not displayed as citations.

**Source:** Source Access and Citation System：

> `evidence.provenance.v1` contains all read or inherited dependencies, not just visible citations.

这里的 read and inherited dependencies 是两类依赖的合称，原文明确“不局限于可见引用”。
人工标签为 supported，MiniCheck 原样重跑仍预测 not_supported。

**输入对照：** 只保留上面的支持句仍误拒。进一步做单处措辞改动：

- 只把 Provenance 换成完整 `evidence.provenance.v1`：仍拒绝。
- 只把 and 换成 or：仍拒绝。
- 保持主体和前半句，只把 “including ones not displayed as citations”
  换成原文的 “not just visible citations”：转为 supported。

**分析：** 这些对照没有支持“主要因为组件名不完整”或“主要因为 and/or”的解释。
更直接的证据是，对“不只可见引用”这一关系的等义转述很敏感。
不能靠保留原句才能通过的表现，证明它已具备稳健的语义蕴含能力。

### EN-Q10-2：加入 original 一词就误拒原文片段复核

**Question:** Which dependencies and Reader checks are retained?

**Claim:** Reader rechecks current permissions, body version, hash and the original excerpt.

**Source:** 同一文档规定 Reader 解析已保存消息的 evidence_ref，然后：

> checks current permission, body version, hash, and excerpt.

人工标签把 Reader 对当前来源的检查转述为 rechecks，excerpt 指该已绑定证据片段，
因此标为 supported。不是凭空增加一个文档外的证据。
MiniCheck 原样重跑仍预测 not_supported，聚焦 Reader 原文句后仍误拒。

**单处措辞对照：**

- 仅 rechecks → checks：仍拒绝。
- 仅 permissions → permission：仍拒绝。
- 仅删去 original，保留 rechecks 和复数 permissions：转为 supported。

**分析：** 在这组对照中，original 是足以改变结果的修饰词。
模型可能把该修饰视作额外限定，也可能只是对措辞敏感；现有实验不能区分两种内部原因。
对原文中的 excerpt 指代应有清晰的标注说明，后续也应区分真正新增限制与无实质增量的修饰。
这不构成删除修饰词即可普遍修复问题的依据。

### EN-Q16-2：提醒与两天纠正要求之间的转述失败

**Question:** What are the stated maintenance deadlines and bot schedule?

**Claim:** Corrections must be made within two days of a formatting correction reminder.

**Source:** User Guide 的 Correction reminders 行描述机器人检查命名和模板格式，
对不合规页面提醒团队联系人，随后规定：

> Please make corrections within **2 days**.

人工标签为 supported，MiniCheck 原样重跑仍预测 not_supported。
仅保留表头和 Correction reminders 行，仍误拒；完整表格改成普通文本，也仍误拒。

**单处措辞对照：** two → 2、删除 formatting、must → should，均没有改变拒绝。
把整句收回到接近原文的 “Please make corrections within 2 days.” 后，才预测 supported。

**分析：** 不能单独归因于数字写法、formatting 或情态词；这些单项改动都没有修复。
原句把上下文中的格式提醒和两天要求合并成时间关系，模型对这种跨句转述不稳定。
需要注意 gold 的时间起点来自该提醒行的语境，而非一个显式时间戳；复核时应记录这一语境依据。

## 这次实验能说明什么

先冻结 26 个英文输入对照，再补 9 个单处措辞对照；均为已知失败后的诊断，不参与选型评分，
不替换原始结果。没有改模型、调阈值、添加业务关键词规则或调用外部 judge。
每次推断前重新验证原来源当前授权和冻结文件/原文，未静默截断，固定官方权重和 EOS 输入方式。
分类器概率只保留在离线诊断文件，不是答案模型自评或正确率。

观察结果是：

1. 三条误放行的原 claim，在缩到相关原句/行后都拒绝；支持上下文中主体、对象和关系干扰的解释。
2. 三条误拒在聚焦原文后仍拒绝；改成更贴近原文的断言才能接受，另有单词删除即可翻转的实例。
3. 同一原文可接受正确陈述和错误陈述，不等于形成了彼此一致的事实判断。
4. 这六条不是输入超长、缺少真实原文或偶然一次运行造成：原样诊断与完整重跑标签均一致。

这些是输入输出层面的证据，不是模型内部注意力或训练原因的证明。
本轮不把诊断改写包装成“六条已修好”，也不自动在生产中缩掉上下文或改写用户断言。

## 对后续实现的影响

保留 MiniCheck 作为唯一实现方向。核验上下文应围绕已绑定 quote，同时保留必要主体、
否定、对比对象、表格行名/表头/单位；上下文范围仍需用新的未见样本验收。
本次三条聚焦成功不证明“越短越好”，删掉关系所需信息同样可能导致错误。

生成断言时使用短而明确的事实句，绑定各自必要原文；不要要求照抄才能过核验。
不能通过删修饰词、补几个年份或数字规则、反复改写直到通过，掩盖语义误判。
MiniCheck 仍输出二分类 supported/not_supported，不伪造矛盾与证据不足的三态解释。

## 运行证据与代码验证

外部运行根目录：`D:/AI-QA-Assistant/claim-verification-20261015/private/`。

- 原英文数据/结果：`english-retest/`，数据 SHA 为
  `8f03ac6b631ff794d18b7c546e906e864108342311a9a8e8ce18dfe9885af3c1`。
- 新单模型完整重跑：`minicheck-selected-replay/`；126 条标签无变化，本地 ACL 副本负例拒绝并恢复。
- 26 项输入诊断：`minicheck-diagnostics/`；预冻结 spec SHA 为
  `224b37a0ba2b1ff00a03e161a94cb6f273224477e5d9ca3643df0e8147a0528c`。
- 9 项单处措辞诊断：`minicheck-wording/`；spec 和结果单独保留。
- Agent 全量：**1009 passed，42.26 秒**，两项既有依赖弃用警告。
  日志 `pytest-minicheck-only-full.log`。未重跑前端或将此称为整站真实问答验收。

删除的权重不在历史输出中复制留存；非权重元数据归档及历史预测不会作为当前模型加载入口。
