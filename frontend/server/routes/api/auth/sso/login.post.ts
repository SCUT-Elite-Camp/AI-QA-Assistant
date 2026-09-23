import { defineHandler, HTTPError } from 'nitro'
import { readValidatedBody } from 'nitro/h3'
import { z } from 'zod'
import { defu } from 'defu'
import { useUserSession } from '../../../../utils/session'
import { useDrizzle, tables, eq } from '../../../../utils/drizzle'

/**
 * POST /api/auth/sso/login
 * SSO / LDAP 登录接口（预留骨架）。
 *
 * 接入汇丰内部 IdP 时，由网关/前置代理完成 SAML/OIDC/LDAP 校验后，
 * 携带已认证的身份信息调用本接口建立会话。生产环境需在启用前
 * 补充签名校验或仅允许内网调用（配合反向代理限制）。
 *
 * 请求体：
 * - userId: 内部用户唯一标识（与 users.id / ssoId 关联）
 * - username: 用户名
 * - name: 显示名
 * - email: 邮箱
 * - departments: 可选，用户所属部门 ID 列表
 */
const ssoLoginSchema = z.object({
  userId: z.string().min(1),
  username: z.string().min(1),
  name: z.string().optional(),
  email: z.string().email().optional(),
  departments: z.array(z.string()).optional(),
})

export default defineHandler(async (event) => {
  // 预留：仅在生产且配置了内部鉴权后启用
  if (process.env.NODE_ENV === 'production' && !process.env.SSO_ENABLED) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Not Found' })
  }

  const body = await readValidatedBody(event, ssoLoginSchema.parse)

  const db = useDrizzle()
  const userId = body.userId

  // 查找或创建用户（优先按 ssoId 关联）
  let [dbUser] = await db
    .select()
    .from(tables.users)
    .where(eq(tables.users.ssoId, userId))

  if (!dbUser) {
    ;[dbUser] = await db
      .select()
      .from(tables.users)
      .where(eq(tables.users.id, userId))
  }

  if (!dbUser) {
    await db.insert(tables.users).values({
      id: userId,
      email: body.email || `${body.username}@sso.local`,
      name: body.name || body.username,
      username: body.username,
      avatar: '',
      provider: 'sso',
      providerId: userId,
      ssoId: userId,
    })
    ;[dbUser] = await db.select().from(tables.users).where(eq(tables.users.id, userId))
  }

  if (dbUser?.disabled) {
    throw new HTTPError({ statusCode: 403, statusMessage: 'Account disabled' })
  }

  // 同步部门关联
  if (body.departments?.length) {
    await db.delete(tables.userDepartments).where(eq(tables.userDepartments.userId, dbUser.id))
    await db.insert(tables.userDepartments).values(
      body.departments.map(departmentId => ({ userId: dbUser.id, departmentId })),
    )
  }

  // 读取当前部门，写入 session 供 Agent 层部门级授权使用
  const memberships = await db
    .select()
    .from(tables.userDepartments)
    .where(eq(tables.userDepartments.userId, dbUser.id))
  const departmentIds = memberships.map(m => m.departmentId)

  const session = await useUserSession(event)
  await session.update(defu({
    user: {
      id: dbUser.id,
      username: dbUser.username,
      name: dbUser.name,
      avatar: dbUser.avatar,
      role: dbUser.role,
      disabled: dbUser.disabled,
      departmentIds,
    },
  }, session.data))

  return {
    success: true,
    user: {
      id: dbUser.id,
      username: dbUser.username,
      name: dbUser.name,
      avatar: dbUser.avatar,
      role: dbUser.role,
    },
  }
})
