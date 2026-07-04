# Agent 层协作准则

本文件约束 `agent-layer/` 目录内的 AI 协作和代码修改。

## 必读文件

在修改 Agent 层代码或文档前，先阅读：

- `docs/development_guide.md`：项目公共开发指南，作为分支、PR、Commit 和目录边界的协作准则。
- `README.md`：Agent 层当前 Q1 范围、运行方式、测试方式和模块分工。
- `docs/API_CONTRACT.md`、`docs/interface_contract.md`：涉及接口变更时必须同步检查。

## 开发边界

- Agent 层开发以 `docs/development_guide.md` 为流程准则。
- 只在 Agent 团队负责范围内修改；不要顺手改 Web、Toolset、Data Persistence 或 Data Pipeline 代码。
- 继续遵守 README 中的 Q1 边界：默认 Mock Retrieval、Mock LLM，不连接真实 HSBC 系统，不写入真实密钥。
- 涉及接口、测试用例或联调记录的改动，需要同步更新 `docs/` 下对应文档。
