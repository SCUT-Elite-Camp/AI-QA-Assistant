import { drizzle } from 'drizzle-orm/libsql'
import { createClient } from '@libsql/client'

import * as schema from '../database/schema'
import { recordDbQuery } from './metrics'
import { logger } from './logger'

export { sql, eq, and, or, asc, desc, inArray } from 'drizzle-orm'

export const tables = schema

let _db: ReturnType<typeof drizzle<typeof schema>> & { $client: ReturnType<typeof createClient> }

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

    // Ensure database tables exist
    try {
      client.execute('CREATE TABLE IF NOT EXISTS topics (id TEXT PRIMARY KEY, title TEXT NOT NULL, main_chat_id TEXT NOT NULL, soul_content TEXT NOT NULL DEFAULT "", description TEXT, weight_mode TEXT NOT NULL DEFAULT "auto", tags TEXT, status TEXT NOT NULL DEFAULT "ready", consecutive_no_new_docs_count INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL)')
      try { client.execute('ALTER TABLE topics ADD COLUMN tags TEXT;') } catch {}
      try { client.execute('ALTER TABLE topics ADD COLUMN status TEXT NOT NULL DEFAULT "ready";') } catch {}
      try { client.execute('ALTER TABLE topics ADD COLUMN description TEXT;') } catch {}
      client.execute('CREATE TABLE IF NOT EXISTS topic_documents (id TEXT PRIMARY KEY, topic_id TEXT NOT NULL, doc_id TEXT NOT NULL, title TEXT NOT NULL, source_url TEXT, snippet TEXT, recall_count INTEGER NOT NULL DEFAULT 1, last_recalled_at INTEGER NOT NULL, score REAL, is_removed INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL)')
      client.execute('CREATE TABLE IF NOT EXISTS message_feedbacks (id TEXT PRIMARY KEY, chat_id TEXT NOT NULL, message_id TEXT NOT NULL, is_favorite INTEGER NOT NULL DEFAULT 0, suggestion_text TEXT, created_at INTEGER NOT NULL)')
    } catch {
      // Ignore
    }

  }
  return _db
}


export type Chat = typeof schema.chats.$inferSelect
export type Message = typeof schema.messages.$inferSelect
export type Vote = typeof schema.votes.$inferSelect
