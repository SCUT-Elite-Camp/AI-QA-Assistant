# Agent 层协作准则

本文件约束 `agent-layer/` 目录内的 AI 协作和代码修改。

## 必读文件

在修改 Agent 层代码或文档前，先阅读：

- `docs/development_guide.md`：项目公共开发指南，作为分支、PR、Commit 和目录边界的协作准则。
- `README.md`：Agent 层当前 CP2/Research 范围、运行方式、测试方式和模块分工。
- `docs/API_CONTRACT.md`、`docs/interface_contract.md`：涉及接口变更时必须同步检查。

## 开发边界

- Agent 层开发以 `docs/development_guide.md` 为流程准则。
- 默认只修改 Agent 团队负责范围；用户明确授权全系统整合时，可修复必要跨层契约，并同步上下游文档与测试。
- Mock 仅用于隔离单元/契约测试；真实验收使用实际模型、检索及原生权限，不允许自动退回 Mock 冒充成功。不连接未经授权的 HSBC 客户系统，不提交真实密钥。
- 当前访问与证据契约以根 `AGENTS.md`、`../docs/access-evidence-architecture.md` 和 `../docs/access-evidence-integration.md` 为准；历史 Q1 无鉴权描述不适用。
- 涉及接口、测试用例或联调记录的改动，需要同步更新 `docs/` 下对应文档。
