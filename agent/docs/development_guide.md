# AI-QA-Assistant 开发指南

## 仓库地址
https://github.com/SCUT-Elite-Camp/AI-QA-Assistant

---

## 分支结构

```
main              ← 稳定版本，不要直接改
dev               ← 集成分支，测试没问题才合进来
web-dev           ← Web 团队开发分支
agent-dev         ← Agent 团队开发分支
toolset-dev       ← Toolset 团队开发分支
data-persistence-dev  ← Data Persistence 团队开发分支
data-pipeline-dev     ← Data Pipeline 团队开发分支
```

---

## 第一次配置（只需做一次）

```bash
# 1. clone 仓库
git clone https://github.com/SCUT-Elite-Camp/AI-QA-Assistant.git
cd AI-QA-Assistant

# 2. 切到你们团队的分支（以 web 团队为例）
git checkout -b web-dev origin/web-dev
```

---

## 日常开发流程

```bash
# 1. 开发前先拉最新代码
git pull origin web-dev

# 2. 写代码...

# 3. 提交
git add .
git commit -m "feat: 简短描述你做了什么"

# 4. 推送到远程
git push origin web-dev
```

---

## 提 PR 合并到 dev

1. 打开仓库主页，会看到黄色提示 **"web-dev had recent pushes"**
2. 点 **Compare & pull request**
3. 确认 base 是 `dev`，compare 是你的团队分支
4. 写清楚这次 PR 做了什么
5. 点 **Create pull request**
6. 等待 review，approve 后合并

---

## Commit 命名规范

| 前缀 | 用途 | 例子 |
|------|------|------|
| `feat:` | 新功能 | `feat: add chat page` |
| `fix:` | 修复 bug | `fix: message history not loading` |
| `chore:` | 配置/依赖更新 | `chore: update requirements.txt` |
| `docs:` | 文档更新 | `docs: update README` |

---

## 目录结构

```
AI-QA-Assistant/
├── web/               ← Web 团队
├── agent/             ← Agent 团队
├── toolset/           ← Toolset 团队
├── data-persistence/  ← Data Persistence 团队
├── data-pipeline/     ← Data Pipeline 团队
└── docs/              ← 公共文档
```

**只在自己团队的文件夹里开发，不要改别人的代码。**

---

## 注意事项

- 不要直接 push 到 `main` 或 `dev`
- 每次开发前先 `git pull` 拉最新代码
- 遇到冲突找队长解决
