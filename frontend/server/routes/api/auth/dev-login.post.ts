import { defineHandler, HTTPError } from 'nitro'
import { readValidatedBody } from 'nitro/h3'
import { z } from 'zod'
import { defu } from 'defu'
import { useUserSession } from '../../../utils/session'
import { useDrizzle, tables, eq } from '../../../utils/drizzle'

const loginSchema = z.object({
  userId: z.string().optional().default('dev-user'),
  username: z.string().optional().default('dev'),
  name: z.string().optional().default('Development User'),
  avatar: z.string().optional().default('https://github.com/nuxt.png'),
  role: z.enum(['admin', 'user']).optional(),
})

/**
 * POST /api/auth/dev-login
 * 开发环境专用登录接口。
 * 仅在 ALLOW_DEV_LOGIN=true 或 NODE_ENV=development 时可用。
 *
 * 用法：
 *   curl -X POST http://localhost:3000/api/auth/dev-login \
 *     -H 'Content-Type: application/json' \
 *     -d '{}' \
 *     -c cookies.txt -b cookies.txt
 *
 * 之后 cookies.txt 中的 session cookie 即可用于所有需要登录的 API。
 */
export default defineHandler(async (event) => {
  const isDev = process.env.NODE_ENV === 'development' || process.env.ALLOW_DEV_LOGIN === 'true'

  if (!isDev) {
    throw new HTTPError({
      statusCode: 403,
      statusMessage: 'Forbidden',
      message: 'Dev login only available in development mode. Set ALLOW_DEV_LOGIN=true or NODE_ENV=development.',
    })
  }

  const body = await readValidatedBody(event, loginSchema.parse)
  const db = useDrizzle()

  // 确保数据库中存在该用户（user_settings 有外键依赖 users 表）
  const [existingUser] = await db.select().from(tables.users).where(eq(tables.users.id, body.userId))
  if (!existingUser) {
    await db.insert(tables.users).values({
      id: body.userId,
      email: `${body.username}@dev.local`,
      name: body.name,
      avatar: body.avatar,
      username: body.username,
      provider: 'github',
      providerId: body.userId,
      role: body.role ?? 'user',
    })
  } else if (body.role) {
    // 开发登录支持临时指定角色，便于测试管理后台
    await db.update(tables.users).set({ role: body.role }).where(eq(tables.users.id, body.userId))
  }

  const [dbUser] = await db.select().from(tables.users).where(eq(tables.users.id, body.userId))

  // 读取当前部门，写入 session 供 Agent 层部门级授权使用
  const memberships = await db.select().from(tables.userDepartments).where(eq(tables.userDepartments.userId, body.userId))
  const departmentIds = memberships.map(m => m.departmentId)

  const session = await useUserSession(event)

  await session.update(defu({
    user: {
      id: body.userId,
      username: body.username,
      name: body.name,
      avatar: body.avatar,
      role: dbUser?.role,
      disabled: dbUser?.disabled,
      departmentIds,
    },
  }, session.data))

  return {
    success: true,
    user: {
      id: body.userId,
      username: body.username,
      name: body.name,
      avatar: body.avatar,
      role: dbUser?.role,
      disabled: dbUser?.disabled,
    },
  }
})
