import { mkdir } from 'node:fs/promises'
import { definePlugin } from 'nitro'
import { migrate } from 'drizzle-orm/libsql/migrator'
import { ensureDrizzleReady, reconcileDrizzleSchema, useDrizzle } from '../utils/drizzle'

export default definePlugin(async () => {
  if (!import.meta.dev) {
    await ensureDrizzleReady()
    return
  }

  await mkdir('.data', { recursive: true })

  try {
    await migrate(useDrizzle(), {
      migrationsFolder: 'server/database/migrations'
    })
  } catch (e) {
    // If tables already exist in local sqlite.db, continue to reconciliation
  }

  // Generated migrations create the legacy core tables on a fresh local DB;
  // reconcile once more so additive columns are also present there.
  await reconcileDrizzleSchema()
})
