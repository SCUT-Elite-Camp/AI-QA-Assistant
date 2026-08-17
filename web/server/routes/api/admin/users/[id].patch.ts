import { defineHandler, HTTPError } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { readValidatedBody } from 'nitro/h3'
import { z } from 'zod'
import { useDrizzle, tables, eq } from '../../../../utils/drizzle'
import { requireAdmin } from '../../../../utils/admin'

const updateUserSchema = z.object({
  email: z.string().email().optional(),
  name: z.string().min(1).optional(),
  username: z.string().min(1).optional(),
  avatar: z.string().optional(),
  role: z.enum(['admin', 'user']).optional(),
  ssoId: z.string().nullable().optional(),
  disabled: z.boolean().optional(),
  departmentIds: z.array(z.string()).optional(),
})

/**
 * PATCH /api/admin/users/:id
 * 编辑用户信息、角色、禁用状态，以及重新分配部门。仅管理员可访问。
 */
export default defineHandler(async (event) => {
  await requireAdmin(event)

  const userId = getRouterParam(event, 'id')
  if (!userId) {
    throw new HTTPError({ statusCode: 400, statusMessage: 'Missing user id' })
  }

  const body = await readValidatedBody(event, updateUserSchema.parse)
  const db = useDrizzle()

  const [user] = await db.select().from(tables.users).where(eq(tables.users.id, userId))
  if (!user) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'User not found' })
  }

  const patch: Record<string, unknown> = {}
  if (body.email !== undefined) patch.email = body.email
  if (body.name !== undefined) patch.name = body.name
  if (body.username !== undefined) patch.username = body.username
  if (body.avatar !== undefined) patch.avatar = body.avatar
  if (body.role !== undefined) patch.role = body.role
  if (body.ssoId !== undefined) patch.ssoId = body.ssoId
  if (body.disabled !== undefined) patch.disabled = body.disabled

  if (Object.keys(patch).length > 0) {
    await db.update(tables.users).set(patch).where(eq(tables.users.id, userId))
  }

  if (body.departmentIds !== undefined) {
    await db.delete(tables.userDepartments).where(eq(tables.userDepartments.userId, userId))
    if (body.departmentIds.length > 0) {
      await db.insert(tables.userDepartments).values(
        body.departmentIds.map(deptId => ({ userId, departmentId: deptId })),
      )
    }
  }

  return { success: true }
})
