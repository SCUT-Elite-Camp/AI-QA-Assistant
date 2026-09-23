import { defineHandler, HTTPError } from 'nitro'
import { readValidatedBody } from 'nitro/h3'
import { z } from 'zod'
import { useUserSession } from '../../utils/session'
import { useDrizzle, tables, eq } from '../../utils/drizzle'

const settingsSchema = z.object({
  theme: z.enum(['light', 'dark', 'system']).optional(),
  primaryColor: z.string().optional(),
  neutralColor: z.string().optional(),
  language: z.enum(['zh-CN', 'en-US']).optional(),
  notificationsEnabled: z.boolean().optional(),
  autoSaveChats: z.boolean().optional(),
  fontSize: z.enum(['small', 'medium', 'large']).optional(),
})

/**
 * POST /api/settings
 * 创建或更新用户设置（upsert）。
 */
export default defineHandler(async (event) => {
  const session = await useUserSession(event)
  const userId = session.data.user?.id

  if (!userId) {
    throw new HTTPError({ statusCode: 401, statusMessage: 'Unauthorized' })
  }

  const body = await readValidatedBody(event, settingsSchema.parse)
  const db = useDrizzle()

  // 检查是否已有设置记录
  const [existing] = await db.select().from(tables.userSettings).where(eq(tables.userSettings.userId, userId))

  const now = new Date()
  const values = {
    userId,
    theme: body.theme ?? existing?.theme ?? 'system',
    primaryColor: body.primaryColor ?? existing?.primaryColor ?? 'blue',
    neutralColor: body.neutralColor ?? existing?.neutralColor ?? 'zinc',
    language: body.language ?? existing?.language ?? 'zh-CN',
    notificationsEnabled: body.notificationsEnabled ?? existing?.notificationsEnabled ?? true,
    autoSaveChats: body.autoSaveChats ?? existing?.autoSaveChats ?? true,
    fontSize: body.fontSize ?? existing?.fontSize ?? 'medium',
    updatedAt: now,
  }

  if (existing) {
    await db.update(tables.userSettings)
      .set({ ...values, createdAt: existing.createdAt })
      .where(eq(tables.userSettings.userId, userId))
  } else {
    await db.insert(tables.userSettings).values(values)
  }

  return { success: true }
})
