import { defineHandler, HTTPError } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { readValidatedBody } from 'nitro/h3'
import { z } from 'zod'
import { useUserSession } from '../../../utils/session'
import { useDrizzle, tables, eq } from '../../../utils/drizzle'
import { isAdmin } from '../../../utils/admin'
import { replaceFileGrants, type FileGrant } from '../../../utils/permission-service'

const updatePermissionSchema = z.object({
  visibility: z.enum(['private', 'shared']).optional(),
  grants: z
    .array(z.object({
      grantType: z.enum(['user', 'department', 'public']),
      grantId: z.string().nullable().optional(),
    }))
    .optional(),
})

/**
 * PATCH /api/files/:id
 * 修改文件可见范围（visibility）与授权列表（grants）。
 * 仅文件所有者或管理员可操作，权限立即生效（不做缓存）。
 */
export default defineHandler(async (event) => {
  const fileId = getRouterParam(event, 'id')
  if (!fileId) {
    throw new HTTPError({ statusCode: 400, statusMessage: 'Missing file id' })
  }

  const session = await useUserSession(event)
  const userId = session.data.user?.id

  if (!userId) {
    throw new HTTPError({ statusCode: 401, statusMessage: 'Unauthorized' })
  }

  const body = await readValidatedBody(event, updatePermissionSchema.parse)
  const db = useDrizzle()

  const [file] = await db.select().from(tables.files).where(eq(tables.files.id, fileId))
  if (!file) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'File not found' })
  }

  const isOwner = file.userId === userId
  if (!isOwner && !(await isAdmin(userId))) {
    throw new HTTPError({ statusCode: 403, statusMessage: 'Only owner or admin can update permissions' })
  }

  if (body.visibility !== undefined) {
    await db.update(tables.files).set({ visibility: body.visibility }).where(eq(tables.files.id, fileId))
  }

  if (body.grants !== undefined) {
    const grants: FileGrant[] = body.grants.map(g => ({
      grantType: g.grantType,
      grantId: g.grantType === 'public' ? null : (g.grantId ?? null),
    }))
    await replaceFileGrants(db, fileId, grants)
  }

  return { success: true }
})
