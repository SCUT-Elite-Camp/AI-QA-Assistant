import { defineHandler, HTTPError } from 'nitro'
import { useUserSession } from '../../utils/session'
import { useDrizzle, tables, eq, asc } from '../../utils/drizzle'

/**
 * GET /api/permission-options
 * 返回用户/部门下拉选项，供文件权限配置选择器使用。登录用户即可访问。
 * 仅暴露最小必要字段（id/name），不泄露邮箱、角色等敏感信息。
 */
export default defineHandler(async (event) => {
  const session = await useUserSession(event)
  if (!session.data.user?.id) {
    throw new HTTPError({ statusCode: 401, statusMessage: 'Unauthorized' })
  }

  const db = useDrizzle()

  const [users, departments] = await Promise.all([
    db.select({
      id: tables.users.id,
      name: tables.users.name,
      username: tables.users.username,
    })
      .from(tables.users)
      .where(eq(tables.users.disabled, false))
      .orderBy(asc(tables.users.name)),
    db.select({
      id: tables.departments.id,
      name: tables.departments.name,
    })
      .from(tables.departments)
      .orderBy(asc(tables.departments.name)),
  ])

  return { users, departments }
})
