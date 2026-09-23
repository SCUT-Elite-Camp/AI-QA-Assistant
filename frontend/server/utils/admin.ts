import { HTTPError } from 'nitro'
import type { HTTPEvent } from 'nitro/h3'
import { useUserSession } from './session'
import { useDrizzle, tables, eq } from './drizzle'

/**
 * 判断用户是否为管理员。每次实时查询数据库，保证角色变更立即生效。
 */
export async function isAdmin(userId: string | null | undefined): Promise<boolean> {
  if (!userId) return false
  const db = useDrizzle()
  const [user] = await db.select().from(tables.users).where(eq(tables.users.id, userId))
  return user?.role === 'admin' && !user.disabled
}

/**
 * 管理员守卫：仅允许 admin 角色的登录用户访问，否则抛出 401/403。
 * 返回当前用户 id 供后续逻辑使用。
 */
export async function requireAdmin(event: HTTPEvent): Promise<{ userId: string }> {
  const session = await useUserSession(event)
  const userId = session.data.user?.id || session.id

  if (!userId) {
    throw new HTTPError({ statusCode: 401, statusMessage: 'Unauthorized' })
  }

  if (!(await isAdmin(userId))) {
    throw new HTTPError({ statusCode: 403, statusMessage: 'Admin access required' })
  }

  return { userId }
}
