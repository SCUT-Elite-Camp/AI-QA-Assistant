import { defineHandler } from 'nitro'
import { useUserSession } from '../../utils/session'
import { useDrizzle, tables, eq } from '../../utils/drizzle'

/**
 * GET /api/settings
 * 获取当前用户的设置，无记录时返回默认值。
 */
export default defineHandler(async (event) => {
  const session = await useUserSession(event)
  const userId = session.data.user?.id

  if (!userId) {
    return getDefaultSettings()
  }

  const db = useDrizzle()
  const [row] = await db.select().from(tables.userSettings).where(eq(tables.userSettings.userId, userId))

  if (!row) {
    return getDefaultSettings()
  }

  return {
    theme: row.theme,
    primaryColor: row.primaryColor,
    neutralColor: row.neutralColor,
    language: row.language,
    notificationsEnabled: row.notificationsEnabled,
    autoSaveChats: row.autoSaveChats,
    fontSize: row.fontSize,
  }
})

function getDefaultSettings() {
  return {
    theme: 'system',
    primaryColor: 'blue',
    neutralColor: 'zinc',
    language: 'zh-CN',
    notificationsEnabled: true,
    autoSaveChats: true,
    fontSize: 'medium',
  }
}
