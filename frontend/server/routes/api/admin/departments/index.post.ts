import { defineHandler, HTTPError } from 'nitro'
import { readValidatedBody } from 'nitro/h3'
import { z } from 'zod'
import { useDrizzle, tables, eq } from '../../../../utils/drizzle'
import { requireAdmin } from '../../../../utils/admin'

const createDepartmentSchema = z.object({
  name: z.string().min(1),
  parentId: z.string().nullable().optional(),
})

/**
 * POST /api/admin/departments
 * 创建部门（可指定上级部门以支持层级）。仅管理员可访问。
 */
export default defineHandler(async (event) => {
  await requireAdmin(event)
  const body = await readValidatedBody(event, createDepartmentSchema.parse)
  const db = useDrizzle()

  const [existing] = await db
    .select()
    .from(tables.departments)
    .where(eq(tables.departments.name, body.name))

  if (existing) {
    throw new HTTPError({ statusCode: 409, statusMessage: 'Department name already exists' })
  }

  const [created] = await db
    .insert(tables.departments)
    .values({
      name: body.name,
      parentId: body.parentId ?? null,
    })
    .returning()

  return { success: true, department: created }
})
