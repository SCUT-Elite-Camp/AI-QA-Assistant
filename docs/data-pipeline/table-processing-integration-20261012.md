# table-processing → optimization 整合记录

日期：2026-10-12。
目标基线：`625885acd652e25fb4fc1c1060632b5ced44bd97`。
来源分支：`origin/table-processing`，头提交 `f44535e`，27 个目标分支尚未包含的提交。
合并保留两条分支历史，不合并到 dev。

## 来源工作与整合修复

来源贡献包括 DOCX/XLSX 原生表格与合并单元格、PDF 版面重建、区域 OCR 融合、
表格后端评分路由、结构化切块、语义/展示文本双视图、跨页坐标和解析诊断，
以及 Milvus 溯源检查、解析报告和可回滚重建工具。

Git 自动合并无文本冲突，但存在接口回退，已在本次合并中修复：

- 保留 HTML/Markdown/DOC/PPTX 入口、`list[Document]` 返回约定及解析器包按需导入。
- 保留 Milvus 环境配置、动态维度、过滤字段、超时和空授权集合拒绝；
  结构化字段新增到既有 schema，按真实字段顺序写列。旧读取继续支持，结构化写入
  在删除向量前拒绝不兼容 schema，避免为了接入功能自动破坏已有集合。
- 补齐来源分支遗漏的 `pipeline.structured_ingestion` 模块；全量、增量、定向入口
  共用双集合索引器，使用语义文本 embedding，保存 Markdown 和实际分页面区域。
- BM25 严格读取指定正文目录。SearchTool 的公开溯源从当前 JSON 中与命中原文精确
  匹配的 chunk 取得，过期向量不获得当前几何/版本证明。
- 保留 Wiki 隔离；离线 Wiki 理解使用原始整表 span，跳过重复的表格行检索视图。
- 维护脚本适配当前 Evidence/Section 集合与外部数据路径，主模块导入无破坏性操作；
  子进程继承一致的 host/port、集合和目录，强制重建遇到失败即触发回滚。
  回滚覆盖改名成功后失联、改名尚未执行及没有旧集合时的新建目标清理。
- MinIO 镜像调整到官方 Quay 地址，保留原版本、服务、端口与卷；
  配置测试改为当前根 Compose，附件配置测试跟随已整合的 Agent 环境模板。
- 更新 README、运行手册及[当前管线契约](DATA_PIPELINE.md)。

维护入口只操作明确配置的企业 Evidence/Section、documents 和 BM25；
不再调用旧的 knowledge_cards/semantic_segments 重建示例。
私有附件服务的解析器、来源权限与证据协议没有被这套企业管线替换。

## 验证

使用独立 managed worktree 的已提交 optimization 基线进行整合；原工作区未提交的
Memory/选中文本问答/流式展示改动不包含在本轮验证或合并提交中。
Python 使用现有 Python 3.11 虚拟环境，前端通过 frozen lockfile 离线安装依赖。

| 检查 | 结果 |
| --- | --- |
| Pipeline + Persistence + Toolset | 672 passed、2 skipped；22 subtests passed |
| 前端 `pnpm test` | 50 个文件、265 项通过 |
| 前端 `vue-tsc --noEmit` | 通过 |
| 前端 `pnpm build` | 通过，SQLite 和构建输出放在 checkout 外 |
| 真实原生 PDF 解析冒烟 | 自建一页 PDF，1 张 accepted 表格、6 个 chunk，区域覆盖率 1.0；所需文字与表格阈值通过 |
| Agent 标准全量收集 | 2 个原有收集错误，未宣称全量通过 |
| Agent 排除这两个旧文件后的最终运行 | 904 passed、19 failed |
| 干净 optimization 同环境对照 | 同样 2 个收集错误；排除后 903 passed、20 failed |
| Agent 失败集合比较 | 最终失败是基线失败的子集，新增失败 0 |
| `git diff --check` | 通过 |

Agent 收集错误是 `test_chat_research_boundary.py` 与 `test_cp2_orchestration.py`
仍导入已移除的 `InMemoryConversationMemory`。其余既有失败涉及匿名测试请求、
Memory visibility cutoff/DTO、旧 Wiki runner 方法、提示字符串、设置环境与 BaseTool
导入身份。一次研究演示用例在最终运行通过，未据此宣称长期稳定修复。
用户原工作区的 Memory 修复未被混入本轮提交来消除这些基线失败。

机器证据目录：
`C:/Users/Hola/.codex/tmp/table-integration-verification/`，包括
`modules-final.xml/log`、`agent-baseline.xml/log`、`agent-integrated.xml/log`、
`agent-baseline-collection.log`、`frontend-build.log` 与 `native-pdf-report.json`。
这些是本机复现索引，不把未提交的源数据、运行库或模型加入 Git。

## 验收限制

两项存储测试跳过不计通过。单元/契约测试使用 fake transport/model/store；
PDF 冒烟实际调用 PyMuPDF 与原生表格解析，但没有调用真实 OCR、LLM 或 embedding/Milvus。
尚未执行真实 BFF session/CSRF、原生 Confluence 权限、三类来源边界及 Research 产品
质量重验，也没有浏览器布局人审或重复稳定性结论。Agent 基线失败仍待单独修复。

本轮合并未执行索引重建、原生源导出、集合切换或数据库迁移；
原始卷、索引、当前运行库和历史评分未改动。部署结构化写入前按当前管线契约创建
新集合并核对 embedding 维度。真实验收仍遵循[运行手册](../access-evidence/access-evidence-runbook.md)
和根 AGENTS，不因本次解析测试通过而放宽来源授权或 Wiki/Research 边界。
