import { defineHandler, HTTPError } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { readValidatedBody } from 'nitro/h3'
import { z } from 'zod'
import { useUserSession } from '../../../utils/session'
import { useDrizzle, tables, eq } from '../../../utils/drizzle'
import { requireFileAccess, replaceFileGrants, type FileGrant } from '../../../utils/permission-service'

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

  const body = await readValidatedBody(event, updatePermissionSchema.parse)
  const db = useDrizzle()

  // 统一的文件访问控制（仅 owner 或 admin 可修改权限）
  const access = await requireFileAccess(db, userId, fileId, { mode: 'manage' })
  if (!access.ok || !access.file) {
    throw new HTTPError({ statusCode: access.statusCode, statusMessage: access.statusCode === 404 ? 'File not found' : access.statusCode === 401 ? 'Unauthorized' : 'Only owner or admin can update permissions' })
  }
  const file = access.file

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
