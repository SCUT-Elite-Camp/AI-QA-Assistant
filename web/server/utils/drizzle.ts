import { drizzle } from 'drizzle-orm/libsql'
import { createClient } from '@libsql/client'

import * as schema from '../database/schema'
import { recordDbQuery } from './metrics'
import { logger } from './logger'

export { sql, eq, and, or, asc, desc, inArray } from 'drizzle-orm'

export const tables = schema

let _db: (ReturnType<typeof drizzle<typeof schema>> & { $client: ReturnType<typeof createClient> }) | undefined

import fs from 'fs'
import path from 'path'

export function useDrizzle() {
  if (!_db) {
    const defaultDbPath = path.resolve(process.cwd(), '../data-persistence/data/sqlite.db')
    fs.mkdirSync(path.dirname(defaultDbPath), { recursive: true })

    const client = createClient({
      url: process.env.TURSO_DATABASE_URL || `file:${defaultDbPath}`,
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
          const queryText = typeof args[0] === 'string' ? args[0] : 'unknown'
          logger.warn({ sql: queryText.slice(0, 200), duration }, 'slow db query')
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

/**
 * Test-only connection reset. Production code must rely on the process-wide
 * client and schema migrations, never on runtime table creation.
 */
export function resetDrizzleForTests(): void {
  if (process.env.NODE_ENV !== 'test') {
    throw new Error('resetDrizzleForTests is only available in tests')
  }

  _db?.$client.close()
  _db = undefined
}


export type Chat = typeof schema.chats.$inferSelect
export type Message = typeof schema.messages.$inferSelect
export type Vote = typeof schema.votes.$inferSelect
