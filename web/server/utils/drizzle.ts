import { drizzle } from 'drizzle-orm/libsql'
import { createClient } from '@libsql/client'

import * as schema from '../database/schema'
import { recordDbQuery } from './metrics'
import { logger } from './logger'

export { sql, eq, and, or, asc, desc, inArray } from 'drizzle-orm'

export const tables = schema

let _db: ReturnType<typeof drizzle<typeof schema>> & { $client: ReturnType<typeof createClient> }

export function useDrizzle() {
  if (!_db) {
    const client = createClient({
      url: process.env.TURSO_DATABASE_URL || 'file:.data/sqlite.db',
      authToken: process.env.TURSO_AUTH_TOKEN,
    })

    const originalExecute = client.execute.bind(client)
    // 包装 execute 方法以记录耗时
    client.execute = async (...args: Parameters<typeof originalExecute>) => {
      const start = Date.now()
      try {
        const result = await originalExecute(...args)
        const duration = Date.now() - start
        recordDbQuery(duration)
        if (duration > 100) {
          const sql = typeof args[0] === 'string' ? args[0] : args[0]?.sql || 'unknown'
          logger.warn({ sql: sql.slice(0, 200), duration }, 'slow db query')
        }
        return result
      } catch (err) {
        const duration = Date.now() - start
        recordDbQuery(duration)
        logger.error({ duration, err }, 'db query error')
        throw err
      }
    }

    _db = drizzle(client, { schema }) as any
  }
  return _db
}

export type Chat = typeof schema.chats.$inferSelect
export type Message = typeof schema.messages.$inferSelect
export type Vote = typeof schema.votes.$inferSelect
