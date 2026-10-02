import { randomUUID } from 'node:crypto'
import { defineHandler, HTTPError } from 'nitro'
import { readValidatedBody } from 'nitro/h3'
import { z } from 'zod'
import { useDrizzle, tables, eq } from '../../../../utils/drizzle'
import { requireAdmin } from '../../../../utils/admin'

const createUserSchema = z.object({
  email: z.string().email(),
  name: z.string().min(1),
  username: z.string().min(1),
  avatar: z.string().optional().default('https://github.com/nuxt.png'),
  role: z.enum(['admin', 'user']).default('user'),
  ssoId: z.string().optional(),
  departmentIds: z.array(z.string()).default([]),
})

/**
 * POST /api/admin/users
 * 创建用户并可选地分配部门。仅管理员可访问。
 */
export default defineHandler(async (event) => {
  await requireAdmin(event)
  const body = await readValidatedBody(event, createUserSchema.parse)
  const db = useDrizzle()

  const [existing] = await db
    .select()
    .from(tables.users)
    .where(eq(tables.users.username, body.username))

  if (existing) {
    throw new HTTPError({ statusCode: 409, statusMessage: 'Username already exists' })
  }

  const [created] = await db
    .insert(tables.users)
    .values({
      email: body.email,
      name: body.name,
      username: body.username,
      avatar: body.avatar,
      provider: 'github',
      providerId: `local-${randomUUID()}`,
      role: body.role,
      ssoId: body.ssoId ?? null,
    })
    .returning()

  if (body.departmentIds.length > 0) {
    await db.insert(tables.userDepartments).values(
      body.departmentIds.map(deptId => ({ userId: created.id, departmentId: deptId })),
    )
  }

  return { success: true, user: created }
})
