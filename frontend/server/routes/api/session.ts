import { defineHandler } from 'nitro'
import { isMethod } from 'nitro/h3'
import { useUserSession } from '../../utils/session'
import { useDrizzle, tables, eq } from '../../utils/drizzle'

export default defineHandler(async (event) => {
  if (isMethod(event, 'DELETE')) {
    const session = await useUserSession(event)
    await session.clear()
    return { success: true }
  }

  const session = await useUserSession(event)
  const data = session.data

  // 实时补充角色、禁用状态与部门信息，保证权限变更、管理后台入口立即可见
  if (data.user) {
    try {
      const db = useDrizzle()
      const [dbUser] = await db.select().from(tables.users).where(eq(tables.users.id, data.user.id))
      if (dbUser) {
        const memberships = await db.select().from(tables.userDepartments).where(eq(tables.userDepartments.userId, dbUser.id))
        return {
          ...data,
          user: {
            ...data.user,
            role: dbUser.role,
            disabled: dbUser.disabled,
            departmentIds: memberships.map(m => m.departmentId),
          },
        }
      }
    } catch {
      // 忽略权限查询失败，避免阻塞会话读取
    }
  }

  return data
})
