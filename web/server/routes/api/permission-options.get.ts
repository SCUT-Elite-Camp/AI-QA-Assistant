import { defineHandler, HTTPError } from 'nitro'
import { useUserSession } from '../../utils/session'
import { useDrizzle, tables, eq, asc } from '../../utils/drizzle'
import { isAdmin } from '../../utils/admin'

/**
 * GET /api/permission-options
 * 返回用户/部门下拉选项，供文件权限配置选择器使用。
 * 仅暴露最小必要字段（id/name/username），不泄露邮箱、角色等敏感信息。
 *
 * 访问收窄：仅限 admin，或当前用户至少拥有一个文件（配置自己文件权限时需要
 * 用户/部门下拉）。普通无文件用户无法调用，杜绝任意注册用户枚举系统用户/部门。
 */
export default defineHandler(async (event) => {
  const session = await useUserSession(event)
  const userId = session.data.user?.id
  if (!userId) {
    throw new HTTPError({ statusCode: 401, statusMessage: 'Unauthorized' })
  }

  const db = useDrizzle()

  // 收窄：admin 或文件 owner 可访问；否则 403。
  if (!(await isAdmin(userId))) {
    const [owned] = await db
      .select({ id: tables.files.id })
      .from(tables.files)
      .where(eq(tables.files.userId, userId))
      .limit(1)
    if (!owned) {
      throw new HTTPError({ statusCode: 403, statusMessage: 'Access denied' })
    }
  }

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
