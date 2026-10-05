# Confluence Cloud 权威正文导出

该工具只执行只读导出，不连接 Milvus，不生成 embedding，也不更新 BM25。

## 配置

复制 `data-pipeline/.confluence.env.example` 为 `.confluence.env`，配置 Cloud
站点地址、账号邮箱和 API Token。系统环境变量优先于文件中的同名配置。

## 导出空间

```powershell
python data-pipeline/confluence_pull.py `
  --space-key TEST `
  --output-dir data-persistence/data/raws/confluence
```

## 导出单页

```powershell
python data-pipeline/confluence_pull.py `
  --page-id 123456 `
  --output-dir data-persistence/data/raws/confluence
```

空间全量导出会在所有页面成功后清理 manifest 中明确登记的失效页面产物。
单页导出不会清理其他页面。每个页面目录包含：

- `index.md`：规范化 Markdown；
- `page.meta.json`：Confluence 来源、版本、哈希和转换告警；
- `section-tree.json`：从 Markdown AST 派生的结构元数据，仅供离线解析和来源定位，不启用独立分层检索；
- 空间根目录 `manifest.json`：页面 ID 到镜像路径的稳定映射。

页面附件只保留链接，本阶段不下载或解析附件正文。无法可靠转换的宏会保留
可见占位符并写入 warnings，避免静默丢失内容。
