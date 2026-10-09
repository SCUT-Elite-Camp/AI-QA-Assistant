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

  // 开发模式免登录自动注入管理员用户
  const isDev = process.env.NODE_ENV === 'development' || !process.env.NODE_ENV || process.env.ALLOW_DEV_LOGIN !== 'false'

  if (!data.user && isDev) {
    try {
      const db = useDrizzle()
      const devUserId = 'dev-user'
      let [dbUser] = await db.select().from(tables.users).where(eq(tables.users.id, devUserId))
      if (!dbUser) {
        await db.insert(tables.users).values({
          id: devUserId,
          email: 'admin@dev.local',
          name: '系统管理员',
          avatar: 'https://github.com/nuxt.png',
          username: 'admin',
          provider: 'github',
          providerId: devUserId,
          role: 'admin',
        })
        const [inserted] = await db.select().from(tables.users).where(eq(tables.users.id, devUserId))
        dbUser = inserted
      } else if (dbUser.role !== 'admin') {
        await db.update(tables.users).set({ role: 'admin' }).where(eq(tables.users.id, devUserId))
        dbUser.role = 'admin'
      }

      const memberships = await db.select().from(tables.userDepartments).where(eq(tables.userDepartments.userId, devUserId))

      const devUserSession = {
        id: devUserId,
        username: dbUser?.username || 'admin',
        name: dbUser?.name || '系统管理员',
        avatar: dbUser?.avatar || 'https://github.com/nuxt.png',
        role: 'admin' as const,
        disabled: false,
        departmentIds: memberships.map(m => m.departmentId),
      }

      await session.update({
        user: devUserSession
      })

      return {
        ...data,
        user: devUserSession
      }
    } catch (e) {
      console.error('Failed to auto create dev user session:', e)
    }
  }

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
