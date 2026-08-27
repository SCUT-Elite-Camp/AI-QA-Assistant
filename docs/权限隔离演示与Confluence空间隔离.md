# 权限隔离演示与 Confluence 空间级权限隔离

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
  - **管理员 (admin)** → role=admin，看全部
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

- **管理员**直接返回"不过滤"（看全部）
- 查询失败默认 **fail-closed**（返回空，拒绝全部），避免权限误开
- 拿到的 doc_id 白名单注入检索，Milvus/BM25 只在这批 doc 里找 → **天然隔离**

---

## 二、Confluence 接入后的空间级权限隔离

### 2.1 为什么是"空间级"

**Confluence 里页面本身没有独立权限**，页面的访问权限完全继承它所属**空间（Space）**的权限方案。所以做到"空间级隔离"就等于实现了页面隔离，无需额外处理页面级权限。

### 2.2 当前的问题

原来的 `confluence_pull.py` 用管理员 token 把空间页面全量抓下来入 Milvus，但**这些文档没有登记到系统的 `files`/`file_permissions` 表** → 它们不在任何普通用户的 doc_id 白名单里 → **对普通用户完全不可见（只有 admin 能看到）**。权限隔离无从谈起。

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

**修改文件 3：`data-pipeline/confluence_pull.py`**
在 `_run_pipeline(d)` 入库后，调用 `register_doc_permissions(...)`，把该文档登记到权限表。

### 2.4 原理闭环

```
Confluence 页面(继承空间权限)
   → confluence_pull.py 抓取入库
   → register_doc_permissions 按 space_key 登记到 files/file_permissions
   → Agent 检索时 get_accessible_doc_ids 计算 doc_id 白名单
   → Milvus/BM25 只在该用户可见的 doc_id 内检索
```

### 2.5 使用方法

```bash
# 1. 配置空间权限映射（编辑 confluence_space_permissions.json，把空间 Key 和可见范围填好）
#    space_key 需与 confluence_pull.py 拉取的 space 一致（默认 test）

# 2. 拉取并入库（自动登记权限）
python data-pipeline/confluence_pull.py test

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
3. **owner 用户**建议用 `demo-admin`（admin），避免 owner 恰好是普通用户造成归属混乱。
4. **权限变更即时生效**：`permission_service` 不做缓存，改配置后重新跑一次 `confluence_pull.py`（或用脚本重登记）即可。
5. 生产环境请务必关闭 `ALLOW_DEV_LOGIN`；空间权限映射要结合 Confluence 侧的空间权限一起维护。

---

## 附：涉及的代码/文件清单

| 文件 | 改动 | 说明 |
|---|---|---|
| `web/src/components/UserMenu.vue` | 修改 | 顶栏用户菜单加「开发者·切换身份」 |
| `data-pipeline/confluence_space_permissions.json` | 新增 | 空间→可见范围映射配置 |
| `data-pipeline/confluence_permission_register.py` | 新增 | 权限登记器（写 web 层 SQLite） |
| `data-pipeline/confluence_pull.py` | 修改 | 入库后调用权限登记 |
