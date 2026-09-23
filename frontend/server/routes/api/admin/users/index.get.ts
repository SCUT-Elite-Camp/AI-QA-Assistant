import { defineHandler } from 'nitro'
import { useDrizzle, tables, desc } from '../../../../utils/drizzle'
import { requireAdmin } from '../../../../utils/admin'

/**
 * GET /api/admin/users
 * 获取所有用户列表（含角色、禁用状态、所属部门）。仅管理员可访问。
 */
export default defineHandler(async (event) => {
  await requireAdmin(event)
  const db = useDrizzle()

  const users = await db.select().from(tables.users).orderBy(desc(tables.users.createdAt))

  const memberships = await db.select().from(tables.userDepartments)
  const deptByUser = new Map<string, string[]>()
  for (const m of memberships) {
    const list = deptByUser.get(m.userId) ?? []
    list.push(m.departmentId)
    deptByUser.set(m.userId, list)
  }

  return users.map(u => ({
    id: u.id,
    email: u.email,
    name: u.name,
    username: u.username,
    avatar: u.avatar,
    provider: u.provider,
    role: u.role,
    ssoId: u.ssoId,
    disabled: u.disabled,
    departmentIds: deptByUser.get(u.id) ?? [],
    createdAt: u.createdAt,
    updatedAt: u.updatedAt,
  }))
})
