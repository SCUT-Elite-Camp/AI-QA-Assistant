# Confluence 全量重拉与原管线观察

日期：2026-10-14。目标是让当前 RAG 空间、本地权威正文、问答索引和 Web 目录一致。
本次没有执行新的问题生成或 Fast 答案质量评测，不将源同步成功当作回答质量通过。

后续已完成当前镜像的 Fast 基线评测与修复复测，见
[2026-10-14 Fast 评测](../testing/quality/fast-evaluation-20261014.md)。上句描述的是全量重拉阶段。

## 当前结果

| 项目 | 核验结果 |
| --- | --- |
| 源站当前页面 / 本地页面记录 | 74 / 74 |
| 源站当前附件 / 本地附件记录 | 24 / 24 |
| 本地来源记录 | 98，每个页面及附件分别保留来源 ID |
| 原管线成功解析并建立文本索引 | 95 |
| 尚未建立文本索引 | 2 个 PNG、1 个 JSON，原文件及来源侧车完整保留 |
| Evidence / BM25 chunks | 1034 / 1034 |
| Section 向量 | 750 |
| 实际 embedding | 本地 BAAI/bge-small-en-v1.5，384 维 |
| 向量与 BM25 / JSON 的来源及块内容 | 对齐，未发现可见重复向量或旧来源混入 |
| 未变更来源仍待入库 | 0 |
| Web 过期知识库目录记录清理 | 65 条；当前目录与 98 条本地记录一致 |
| 开发者账号原生 read 检查 | 98 / 98，仍使用 native 模式 |
| Agent `/ready` / 来源目录 | HTTP 200 / HTTP 200，目录为 98 条 |
| 实际 vector / bm25 / hybrid 冒烟 | 9 次查询有结果，命中均属于当前投影；未据此计算质量成绩 |

源站第二次枚举仍为 74 个页面、24 个附件；未发现页面版本/正文变动、附件版本/归属/大小变动，
也未发现新增 ID。所有页面 XHTML/Markdown 哈希及附件原文件 SHA-256 与导出 manifest 对齐。

## 使用原有管线

先移出旧 `documents`、`raws` 和 BM25，再完整导出当前页面及实际下载每页附件。
页面 exporter 与新增附件下载入口都只获取源文件；实际入库使用原有
`pipeline.auto_process.auto_process_raws(force=True, strict=True)`，经原生 parser、
`prepare_ingestion_chunks`、实际 embedding、Evidence/Section 写入、JSON 保存和 BM25 发布。
出现失败后通过同一原管线增量续跑；最后重处理未完成全局索引发布的投影。

活动目录为工作区 `data-persistence/data`。Agent、Research、BM25 与 Milvus 配置同时指向本批数据。
新的 Evidence/Section 集合为 `rag_current_20261014`、`rag_sections_20261014`。
旧 Milvus 内部通道故障无法靠重启恢复，因此在原本的回环端口 19530/9091 重建服务，
旧容器和卷保留、停用；当前 Compose 配置位于本机运行产物目录。
旧实验目录的活动语料及 BM25 已移出；此前不完整旧题生成产物标为停用。

## 运行时发现与处理

1. 页面导出只保存附件链接：补充按页分页枚举、二进制下载、大小/hash 校验和独立附件 manifest。
2. XLSX 合并区域超出非空单元格边界：扩展表格边界到完整合并跨度，真实附件重新解析成功。
3. Markdown 附件按父页面 ID 生成身份：改为真实 attachment ID，避免附件覆盖页面，原生附件解析器使用同一身份规则。
4. 增量判断混用来源 ID/更新时间与文件路径 ID/mtime：统一身份、来源版本/hash/更新时间，验证未变化数据不会重入库。
5. 附件消失但父页面仍在时未撤回：使用成功的完整附件 manifest 撤回；不完整目录不作为撤回证据。
6. Milvus 中文长标签超出 VARCHAR 字节上限：标签按 UTF-8 字节截取，完整标题及证据正文仍保存于 JSON。
7. 中断后已写向量的投影未完成 BM25 发布：增量续跑识别 `export_ready`/`partial`，补齐发布状态。
8. Root Agent 与 Web 的服务端认证配置不一致：对齐忽略的私有配置，实际鉴权来源目录与原文接口已验证。

当前原管线没有 PNG/JSON 文本解析器，这 3 个附件明确标为未索引，未创建虚构正文。
一份 PDF 的诊断包含 Camelot/GMFT/Paddle 可选后端缺失，未得到结构化表格；原生文本保留。
没有修改历史测试报告成绩，没有放宽源站权限，也没有将旧未知来源记录回填成可信来源。

## 检查与运行证据

- Agent 全量回归：949 passed。
- Pipeline/Toolset 全量回归：591 passed；另有 22 个 subtests，不能与测试数相加。
- 存储 VARCHAR 相关测试：16 passed；最终修改组件组合检查为 21 passed，与前述用例有重叠。
- 初次全模块测试的失败记录保留；部分既有 Storage 测试假定默认环境/连接调用形式，Compose 测试的镜像来源断言也与现有配置不同，未声称全仓库测试全绿。
- 实际服务验证采用真实本地 embedding、Milvus、原生 Confluence read 与鉴权 Agent 来源接口，无模型回答质量验收。

本机证据目录：`D:/AIQA/confluence-refresh-20261014/`。主要文件为
`live-reconciliation.json`、`reconciliation-report.json`、`agent-api-verification.json`、
`retrieval-smoke.json`、`original-pipeline-*.log` 及各测试日志。
旧工作区语料备份在忽略的 `.local-backups/confluence-refresh-20261014/`，旧实验语料位于证据目录的 `retired-lab/`。
原始导出、正文、数据库和凭据不纳入 Git。
