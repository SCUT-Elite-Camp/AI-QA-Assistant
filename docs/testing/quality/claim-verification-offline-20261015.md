# 断言核验器离线对照

后续：用户要求默认测试全部采用英文，已完成[全英文复测](claim-verification-english-20261015.md)。
本文保留混合语言轮次的原始结果；当前英文选型应读取新报告。

日期：2026-10-15。承接[绑定与独立校验方案](claim-binding-verification-plan-20261015.md)。

## 当前结论

两个候选均未达到可以直接启用答案拦截的可靠程度。留出集的 24 条负例中，
NLI 误放行 4 条（16.7%），MiniCheck 误放行 2 条（8.3%）；12 条正确断言分别误拒
1 条（8.3%）和 5 条（41.7%）。开发集的零误放行没有泛化到留出文档。

NLI 识别了真实 Fast 回答中无原文支持的 2023 年，同时接受负责人和查询数量两条正确断言。
MiniCheck 拒绝了这三条断言，其中两条属于误拒。NLI 的中文召回和耗时使其仍有后续研究价值，
但留出结果不支持宣称它全面优于 MiniCheck，更不支持上线门禁。

本轮只新增离线 runner，没有给 Fast 或 Thinking 接入语义门禁。
现有绑定结果仍是 `validation_kind=binding`、`semantic_validation=not_performed`。
Fast 的生成次数和流程保持当前契约；没有答案模型自评分数，也未调用外部 judge。

## 数据与复核方法

先读取当前允许访问的真实 Confluence 导出文档，由 Codex 逐条构造、核对断言和理由，
冻结标签后才执行分类器。项目文档与 Eval KB 未混用。
这里的 gold 是相对所提供原文的支持关系，不表示历史文档描述的行为仍是当前系统行为。
复核者为 Codex，没有独立人工复核，不能称为人审验收。

| 集合 | 文档 / 问题 | 断言数 | 用途 |
| --- | --- | --- | --- |
| 开发集 | 7 / 14 | 84 | 比较候选、了解失败类型 |
| 文档互斥的留出集 | 3 / 6 | 36 | 锁定候选后只运行一次，不调参 |
| 已知错误回归 | 1 / 1 | 6 | 围绕已见的 Preliminary Ideas 问题构造正反例 |
| 真实回答的原始断言 | 同一已见问题 | 3 | 上一轮 Fast 实际生成内容，单独报告 |

共 20 个新问题的 120 对人工构造断言，另有 6 对已见回归和 3 对真实生成断言。
前两者不能冒充自然生成错误分布；最后三条也不能当未见留出集。
所有来源原文均为英文，断言分英文与中文；未覆盖中文原文或图片。
开发集每类 gold 各 28 条，留出集每类各 12 条；回归集每类各 2 条。
类别包括转述、负责人/角色交换、数字、补年份、否定反转、计划当完成、表格错列、
无关证据、多源支持和只支持一部分的复合断言。小样本不足以逐类证明普适性。

初版数据冻结后，在任何分类器推断前将回归表格片段缩为表头和目标行；标签没有修改，
父版本继续保留。最终输入 SHA-256：

```text
cases.v2.json
1d22e07bb504ba5e96113d54c71540ef34fc81f70896d2ebbf632c21f8c7fc49
observed_cases.json
299ebcd2904875ab49924dccc7bef71736fff9048ed5b606036af85d6dbf0e2f
runner-frozen.py
ee0044d9796d373a1c99cd1e9be52ee467b5b776d68b8bbbf78b576ee9c85ed3
```

`private/selection.json` 在留出集推断之前记录：NLI 为后续研究候选，两个模型均使用训练标签
argmax，不调阈值；不批准在线门禁。留出结果不用于修改断言、标签、模型或策略。

## 模型与执行条件

| 项目 | 多语言 NLI | MiniCheck |
| --- | --- | --- |
| 官方模型 | `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` | `lytang/MiniCheck-DeBERTa-v3-Large` |
| 固定修订 | `b5113eb38ab63efdd7f280f8c144ea8b13f978ce` | `2f2d01a54fa022a7ffadb76260e1ea8bc88c82bb` |
| 参数数 | 278,811,651 | 435,063,810 |
| 原生输出 | entailment / neutral / contradiction | 0 / 1（二分类） |
| 输入 | premise / hypothesis 配对 | 原文 + EOS + 断言 |

MiniCheck 输入遵循[作者的 encoder 实现](https://github.com/Liyan06/MiniCheck/blob/main/minicheck/inference.py)。
它的二分类“不支持”未被伪装成能区分矛盾和证据不足。
两者均使用官方训练权重；固定修订、文件大小和 SHA 对照官方文件元数据核实，加载诊断无
missing/mismatched/unexpected keys 或 error messages；不执行远程自定义代码。
模型信息见 [NLI 官方模型卡](https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7)
和 [MiniCheck 官方模型卡](https://huggingface.co/lytang/MiniCheck-DeBERTa-v3-Large)。

```text
NLI model.safetensors SHA-256
7c8e29f1115986d032e92b0fbaa0bdef1062a46f658b08705f237c05014a8541
MiniCheck pytorch_model.bin SHA-256
32ced784f4831d5f324a072e43b96d4072cac4bf41042bc42243605ffbbccbdf
```

Windows CPU、float32、4 个 Torch 线程、batch=4，未使用 CUDA。
Torch 2.12.1+cpu、Transformers 5.17.0；隔离环境仅补装 sentencepiece 0.2.2。
输入均不超过 512 token（本次最长 NLI 263、MiniCheck 223）；超长将停止，未静默截断。
模型顺序执行，没有通过 API 发送私有原文。

## 质量结果

误放行：gold 为矛盾/证据不足，却预测 supported；误拒：gold 为 supported，却没有放行。
二者分母不同，不能合成一个准确率掩盖错误。

| 集合 | NLI 误放行 | NLI 误拒 | MiniCheck 误放行 | MiniCheck 误拒 |
| --- | --- | --- | --- | --- |
| 开发集 | 0 / 56 | 1 / 28 | 1 / 56 | 10 / 28 |
| 文档互斥留出集 | 4 / 24 | 1 / 12 | 2 / 24 | 5 / 12 |
| 已知错误回归 | 0 / 4 | 0 / 2 | 0 / 4 | 1 / 2 |
| 实际生成的三条断言 | 0 / 1 | 0 / 2 | 0 / 1 | 2 / 2 |

留出集按同一固定策略各执行一次。英文负例两模型均误放行 2/12；中文负例 NLI 2/12、
MiniCheck 0/12。正确英文断言误拒 NLI 1/6、MiniCheck 0/6；正确中文断言 NLI 0/6、
MiniCheck 5/6。MiniCheck 的中文低放行率同时拒绝了大部分正确断言。

开发集加构造回归共 90 条：NLI 英文正确断言误拒 1/15、中文 0/15；
MiniCheck 英文误拒 1/15、中文 10/15。英文/中文各有 30 条负例，NLI 均无误放行；
MiniCheck 英文误放行 1/30、中文 0/30。中文误拒集中，不能只看它的低误放行率。

明确失败实例：

- NLI `Q05-1`：原文支持使用 RRF 融合向量和 BM25 排名，分类器误判为矛盾。
- MiniCheck `Q11-3`：原文说只读 exporter，反向断言“exporter 重写页面正文”被误放行。
- 实际 `LIVE-2`：“完成日期为 2023 年 7 月 30 日”，原文只有 July 30。
  NLI 判证据不足；MiniCheck 判不支持，但同时误拒真实负责人和最多三条查询。

留出失败由 Codex 再次对照原始片段，标签未修改：

| 病例 | 原文与错误断言的关系 | NLI | MiniCheck |
| --- | --- | --- | --- |
| Q16-3 | 项目文档更新期限为 3 天，把另一表格行的纠正期限 2 天挪过来 | 误放行 | 误放行 |
| Q17-4 | 明确要求 Web/Agent 同一权限库，断言两者可以互不相关 | 误放行 | 拒绝 |
| Q18-3 | `/health` 只证明进程存活，断言它证明检索资源就绪 | 误放行 | 误放行 |
| Q18-4 | 原文指定 19539/9099，断言改为 19530/9091 | 误放行 | 拒绝 |
| Q19-1 | 原文明确由 BFF session 构造 Agent 身份上下文，正确转述 | 误拒 | 放行 |

这些结果说明，即使输入保留了表头、否定和限定词，分类器也可能只抓到局部相关内容。
本轮没有加关键词、数字或年份补丁去修复这些已见题，也没有根据留出预测调参。

NLI 也不是完美的三态分类：开发集 28 条矛盾中 3 条预测为证据不足，
28 条证据不足中 1 条预测为矛盾。它们在“不放行”策略下均属拒绝，语义类别仍有误差。
本轮没有超长或其他 needs_review 样本，不代表异常路径已通过真实质量验收。

## 耗时与资源

单条 forward：选六个开发病例，各重复两次，共 12 次；先以公开合成句预热。
统计不含加载、tokenization、权限、文件 hash 检查和最终释放；不是完整请求延迟。
没有用 batch 均摊吞吐冒充单条耗时。

| 指标 | NLI | MiniCheck |
| --- | --- | --- |
| 单条 forward p50 | 217.8 ms | 1169.6 ms |
| 单条 forward p95 | 242.9 ms | 1241.2 ms |
| 该进程峰值工作集 | 1919.5 MiB | 1945.8 MiB |
| 模型/分词器加载 | 3.23 s | 0.97 s |

12 个测点的 p95 是本组最大值，不能解释为生产 SLA；加载时间受文件缓存影响，不能用来比较
冷启动优劣。内存是整个 Python 进程的工作集，包含运行依赖，不是单独权重或 GPU 显存。
现有 Fast 回答通常有多条断言，不能直接把一条的 p95 当作整条答案的新增耗时。

## 权限、版本与运行证据

runner 在初始输入、每批 forward、每次单条 benchmark 和最终结果释放前调用真实
PermissionService，要求本地 ACL 与 native Confluence 绑定/权限通过；随后核对实际源文件
SHA、文档身份和原文字符位置。源文件变动即停止。
这核验冻结导出原文的支持关系，不宣称重新导出了最新 Confluence 正文。

显式负例文档为真实 `Local Setup`（`0795387ec022850d5bcf9601c4f0e80f`）。
仅在带 disposable 标记的 SQLite 副本撤去本地授权，实测真实 ACL 拒绝，finally 恢复副本。
原运行数据库未改动。此项只证明本地 ACL 拒绝边界，不是 native 拒绝、线上撤权竞态、
BFF/CSRF、检索或完整问答验收。

首次 NLI 开发推断完成 90 条，但 summary 写出因加载诊断返回 set 而失败。
修复仅将诊断 set 序列化为列表，保留失败目录，再用同一冻结输入完整重跑；90 条标签无变化。
另一个前置 ACL 副本探针因原环境只有一个用户而停止，修改为只在副本创建临时 owner，
finally 恢复。前置失败日志也保留，不算最终运行通过。

所有私有原文、标签、预测、模型、日志与数据库均在 checkout 外：

```text
D:/AI-QA-Assistant/claim-verification-20261015/
  models/{mnli,minicheck}/
  private/cases.v2.json
  private/observed_cases.json
  private/selection.json
  private/results-manifest.json
  private/{mnli,minicheck}-development*/
  private/{mnli,minicheck}-observed/
  private/{mnli,minicheck}-holdout/
```

仓库入口为 `agent/eval/claim_verification_acceptance.py`，使用方式见
[eval README](../../../agent/eval/README.md)。它未被产品运行链路调用。

`results-manifest.json` 保留最终六次运行的 summary、逐条预测、ACL 探针和加载诊断文件 SHA，
并关联留出运行前的选型记录。保留集合与已见回归分别汇总，不用混合总分替代留出结论。

## 代码验证

新增 9 项隔离单元测试通过，覆盖误放行统计、未核验不算通过、冻结数据变更、
开发/留出文档重叠、当前权限/文件 hash/原文漂移，以及 ACL 副本在成功和异常时恢复。
单元测试使用假 transport/provider，只验证这些程序边界，不计入上述真实分类质量结果。

从 `agent/` 运行全量 `python -m pytest`，使用 checkout 外的独立 basetemp：
**998 passed，26.43 秒**，两项既有依赖弃用警告。日志为外部目录 `private/pytest-full.log`。
本轮没有修改前端或 HTTP/SSE 契约，没有将这次离线运行称为整站端到端验收。

## 后续决策

保留 NLI 为后续 Thinking 影子核验候选；当前不直接开启整条拒绝门禁。
需要追加自然生成样本、中文原文、复杂表格/多源关系和复合断言，评估误拒带来的完整答案损失，
并测量包含当前权限/版本检查的整轮耗时。影子结果也必须与断言及证据版本关联。
任何后续实际启用都不能把本轮小样本的零误放行解释为可靠性保证。

Fast 若启用独立分类器，就新增一次或多次模型推断；必须先明确是否允许改变“一次模型调用”
的现有契约。当前没有对此作隐含变更。
