# 权限隔离：本地 ACL 与 Confluence 原生权限

> 更新：2026-10-09。本地空间映射只能登记应用 ACL，不能替代源站有效权限。
> 旧演示中的 group-a/group-b 需要各自明确的 Confluence account/site 绑定才能
> 读取企业页。当前架构与实际验收见[访问边界](access-evidence-architecture.md)
> 和[整合报告](pr63-integration-acceptance.md)。以下场景是本地 ACL 演示，不是全角色原生权限验收记录。

> 面向：金融 RAG 项目组 · AI 知识分享
> 本文档包含两部分：
> - **第一部分**：本地系统的「项目组权限隔离」演示脚本（改了一处前端，方便切换身份）
> - **第二部分**：Confluence 接入后的「空间级权限隔离」实现说明与验证方法

---

## 一、本地系统权限隔离演示

### 1.1 背景与目标

我们系统的权限模型基于 **部门（department）** 与 **文件可见性（visibility）**：

| 概念 | 说明 | 对应"项目组" |
|---|---|---|
| 部门 | 用户的组织归属 | **项目组** |
| 组内文件 | `file_permissions` 授权给某部门 | 项目组内文件 |
| 公开文件 | `visibility = 'shared'` | 全员公开文件 |

**演示目标**（复用你提的场景）：
1. 项目组 A 的 1 号用户上传一个**公开文件** → 项目组 B 的用户**能看到**（shared 全可见）
2. 项目组 A 的 1 号用户上传一个**组内文件**（授权给部门 A）→ A 组**能看到**，B 组**看不到**

### 1.2 前置准备：身份切换器（已改好的前端）

**问题**：之前很难切换成某个普通用户登录（前端只有写死登录 `dev-user` 的开发登录按钮）。

**解决**：在**右上角用户菜单**里加了一个「**开发者 · 切换身份**」分组，复用后端已有的 `POST /api/auth/dev-login` 接口，可在 UI 上直接切换身份：

- 顶栏右上角点开**用户头像菜单**
- 在「开发者 · 切换身份」下点选：
  - **管理员 (admin)** → 本地管理角色；不绕过 Confluence 原生权限
  - **项目组A用户** (group-a) → 普通用户
  - **项目组B用户** (group-b) → 普通用户
- 点选后立即以该身份登录（自动建号 + 刷新会话），再次点开菜单即切换

> **注意**：该切换器走的是开发登录，要求后端 `NODE_ENV=development` 或 `.env` 里设了 `ALLOW_DEV_LOGIN=true`。生产环境不可用（接口本身会返回 403）。

### 1.3 演示准备（一次性）

开始演示前，先建好部门和用户归属，让"项目组 A/B"成立：

1. **建部门**：管理后台 → 组织/部门 → 新建两个部门：`项目组A`、`项目组B`
2. **建用户并分配部门**（管理后台 → 用户）：
   - `group-a` 用户 → 归属 `项目组A`
   - `group-b` 用户 → 归属 `项目组B`
   - （记下部门 ID，后面授权文件要用）

> 如果不想手工建，也可用 `dev-login` 自动建号后，再通过管理后台把用户拖进对应部门。

### 1.4 场景一：公开文件 → B 组可见

| 步骤 | 操作 | 当前身份 | 预期结果 |
|---|---|---|---|
| 1 | 顶栏切到「项目组A用户」 | group-a | 菜单显示 group-a |
| 2 | 进入「文件」页，上传一个文件，可见性选 **公开（shared）** | group-a | 上传成功，出现在文件列表 |
| 3 | 顶栏切到「项目组B用户」 | group-b | 菜单显示 group-b |
| 4 | 进入「文件」页 | group-b | **能看到 group-a 上传的公开文件** |
| 5 | 对文件提问 | group-b | Agent 能检索到该文件内容 |

**结论**：公开文件对所有项目组可见 ✅

### 1.5 场景二：组内文件 → B 组不可见

| 步骤 | 操作 | 当前身份 | 预期结果 |
|---|---|---|---|
| 1 | 顶栏切到「项目组A用户」 | group-a | 菜单显示 group-a |
| 2 | 进入「文件」页，上传一个文件，可见性选 **私有（private）**，并授权给 `项目组A`（部门） | group-a | 上传成功 |
| 3 | 顶栏切到「项目组A用户」保持不动（或重新登录 group-a） | group-a | 文件列表**能看到**组内文件 |
| 4 | 对组内文件提问 | group-a | Agent **能**检索到 |
| 5 | 顶栏切到「项目组B用户」 | group-b | 菜单显示 group-b |
| 6 | 进入「文件」页 | group-b | **看不到**该组内文件 |
| 7 | 对该组内文件提问 | group-b | Agent **检索不到**该文件内容 |

**结论**：组内文件仅项目组 A 可见，项目组 B 隔离 ✅

### 1.6 权限校验的底层原理（给听众讲清楚）

Agent 每次检索前会执行一次白名单计算（`permission_service.get_accessible_doc_ids`），规则：

```
可访问文件 =
    自己上传的（owner）                       OR
    visibility = 'shared'（全员公开）         OR
    file_permissions 授权给：
         public 全员  |  user 当前用户  |  department 当前用户所属部门
```

- 本地管理员角色不绕过启用状态、显式账号绑定或 Confluence 原生权限；strict 接口最终仍是有限 doc ID 集合
- 查询失败默认 **fail-closed**（返回空，拒绝全部），避免权限误开
- 拿到的 doc_id 白名单注入检索，Milvus/BM25 只在这批 doc 里找 → **天然隔离**

---

## 二、Confluence 接入后的空间级权限隔离

### 2.1 不以空间映射替代有效权限

空间映射是本地授权登记策略，不足以证明每个页面对当前源站账号可读。
在线流程用明确的站点/account ID，对具体 page 调用原生 `permission/check`
验证 `read` 权限；本地 allowed 集合与源站检查结果取交集。仅拥有导出 token、
本地 owner/admin 或 shared 标记，不会自动获得 Confluence 访问权。

### 2.2 当前的问题

早期导出/入库与本地 `files/file_permissions` 登记不一致，普通用户无法检索。
目前 `confluence_pull.py` 的 Cloud exporter 是只读正文导出，不负责自动入 Milvus
或授予问答权限；登记器仍可作为显式本地 ACL 操作，但不等于在线源站授权。

### 2.3 解决方案（已实现的代码改动）

引入「**空间 → 可见范围**」映射，入库时把每个 Confluence 文档登记到权限体系：

**新增文件 1：`data-pipeline/confluence_space_permissions.json`**（空间权限映射配置）

```json
{
  "spaces": {
    "test": {
      "visibility": "shared",          // 该空间 → 全员可见
      "owner_user_id": "demo-admin",   // 归属用户（files.user_id）
      "grants": []                     // 无需额外授权
    },
    "fin-report": {
      "visibility": "private",
      "owner_user_id": "demo-admin",
      "grants": [
        { "type": "department", "grant_id": "<部门ID>", "grant_name": "金融研发部" },
        { "type": "user", "grant_id": "group-a", "grant_name": "A组用户" },
        { "type": "public" }
      ]
    }
  },
  "defaults": {
    "owner_user_id": "demo-admin",
    "visibility": "private"
  }
}
```

**新增文件 2：`data-pipeline/confluence_permission_register.py`**
提供 `register_doc_permissions(doc_id, title, source_url, space_key, ...)`：
- 按 `space_key` 读取映射配置，决定 `visibility` 和 `grants`
- **幂等** upsert 到 `files` 表（`doc_id` 唯一索引，重复拉取不产生重复记录）
- 清空旧 `file_permissions` 后按策略重写授权（public / user / department）
- owner 用户在 `users` 表不存在时自动补建
- 登记失败只记 warning，**不阻断** Confluence 入库主流程

`data-pipeline/confluence_pull.py` 当前导出入口见[Confluence 导出说明](../data-pipeline/docs/Confluence导出.md)。
历史自动导入片段不是当前 exporter 的行为；管理员需显式选择导入/登记策略并核对索引与权威正文一致。

### 2.4 原理闭环

```
只读 Confluence 正文导出 → 显式建立权威投影/索引与本地 ACL
   → 当前启用身份 + 显式源站账号/站点绑定
   → 本地 ACL ∩ 原生页面 read 权限
   → 只在该集合内检索/读取，核对版本/hash
   → 每次模型调用、回答释放、历史/Memory/Reader 再检查
```

### 2.5 使用方法

```bash
# 1. 配置空间权限映射（编辑 confluence_space_permissions.json，把空间 Key 和可见范围填好）
#    space_key 需与 confluence_pull.py 拉取的 space 一致（默认 test）

# 2. 拉取并入库（自动登记权限）
python data-pipeline/confluence_pull.py --space-key TEST --output-dir data-persistence/data/raws/confluence

# 3. 验证（可选）：用 agent 层权限服务确认不同用户的可访问集合
cd agent && python -c "from agent.service.permission_service import PermissionService; ps=PermissionService(); print(ps.get_accessible_doc_ids('group-a'))"
```

### 2.6 已验证的隔离效果（实测）

用映射配置（`test` 空间 shared、`secret` 空间仅授权研发部+group-a）实际跑通权限服务：

| 文档 | 用户 | 期望 | 实测 |
|---|---|---|---|
| secret 空间文档 | 研发部成员 | 可见 | ✅ 可见 |
| secret 空间文档 | group-a（user 授权） | 可见 | ✅ 可见 |
| secret 空间文档 | dev-user（无授权） | 不可见 | ✅ 不可见 |
| test 空间文档（shared） | dev-user | 可见 | ✅ 可见 |

### 2.7 注意事项

1. **`space_key` 必须在映射配置里**，否则落到 `defaults`（默认 private，仅 owner 可见 → 对普通用户不可见）。
2. **`grant_id`（部门/用户 ID）要用系统里真实的 ID**（部门 ID 在管理后台查，用户 ID 用 `dev-login` 的 `userId`）。Confluence 的 user/group 无法自动对到系统用户，需要人工映射。
3. 本地 owner 只负责登记归属，不替代当前调用者的源站授权；不应靠 admin 绑定给普通用户兜底。
4. 当前 strict 权限与 Reader 不缓存正向授权；更改映射仅改变本地 ACL，还必须核对源站的当前 `read`。导出不会自动重登记授权。
5. 生产环境请务必关闭 `ALLOW_DEV_LOGIN`；空间权限映射要结合 Confluence 侧的空间权限一起维护。

---

## 附：涉及的代码/文件清单

| 文件 | 改动 | 说明 |
|---|---|---|
| `web/src/components/UserMenu.vue` | 修改 | 顶栏用户菜单加「开发者·切换身份」 |
| `data-pipeline/confluence_space_permissions.json` | 新增 | 空间→可见范围映射配置 |
| `data-pipeline/confluence_permission_register.py` | 新增 | 权限登记器（写 web 层 SQLite） |
| `data-pipeline/confluence_pull.py` | 修改 | 入库后调用权限登记 |
