import { describe, expect, it } from 'vitest'
import { createClient } from '@libsql/client'
import { drizzle } from 'drizzle-orm/libsql'
import { migrate } from 'drizzle-orm/libsql/migrator'

describe('fresh database migrations', () => {
  it('creates the Topic and attachment tables without an additive-schema prepass', async () => {
    const client = createClient({ url: 'file::memory:' })
    try {
      await migrate(drizzle(client), { migrationsFolder: 'server/database/migrations' })
      const tables = await client.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('topics','topic_members','attachment_batches','attachments','message_attachments','library_cleanup_jobs')",
      )
      expect(new Set(tables.rows.map(row => String(row.name)))).toEqual(new Set([
        'topics', 'topic_members', 'attachment_batches', 'attachments', 'message_attachments',
        'library_cleanup_jobs',
      ]))
    } finally {
      client.close()
    }
  })
})
