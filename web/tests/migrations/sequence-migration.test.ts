import { createClient } from '@libsql/client'
import { cp, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { drizzle } from 'drizzle-orm/libsql'
import { migrate } from 'drizzle-orm/libsql/migrator'
import { describe, expect, it } from 'vitest'

describe('migration baseline', () => {
  it('creates the current application tables in an isolated temporary database', async () => {
    const databaseUrl = process.env.TURSO_DATABASE_URL
    expect(databaseUrl).toMatch(/^file:/)

    const client = createClient({ url: databaseUrl! })
    try {
      const result = await client.execute({
        sql: "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
      })
      const tableNames = result.rows.map(row => String(row.name))

      expect(tableNames).toEqual(expect.arrayContaining([
        '__drizzle_migrations',
        'chats',
        'messages',
        'message_feedbacks',
        'topic_documents',
        'topics',
        'users',
        'votes'
      ]))
    } finally {
      client.close()
    }
  })

  it('resets the module-scoped Drizzle client between test environments', async () => {
    const { resetDrizzleForTests, useDrizzle } = await import('../../server/utils/drizzle')
    const first = useDrizzle()

    resetDrizzleForTests()

    expect(useDrizzle()).not.toBe(first)
  })

  it('creates the sequence and revision columns required by the lifecycle', async () => {
    const client = createClient({ url: process.env.TURSO_DATABASE_URL! })
    try {
      const [chatColumns, messageColumns] = await Promise.all([
        client.execute("PRAGMA table_info('chats')"),
        client.execute("PRAGMA table_info('messages')")
      ])

      expect(chatColumns.rows.map(row => String(row.name))).toEqual(expect.arrayContaining([
        'history_revision',
        'next_message_sequence'
      ]))
      expect(messageColumns.rows.map(row => String(row.name))).toEqual(expect.arrayContaining([
        'history_revision',
        'request_id',
        'sequence'
      ]))
    } finally {
      client.close()
    }
  })

  it('migrates a database previously repaired by the retired runtime bootstrap', async () => {
    const fixtureDirectory = await mkdtemp(join(tmpdir(), 'ai-qa-memory-legacy-migration-'))
    const legacyMigrationsDirectory = join(fixtureDirectory, 'legacy-migrations')
    const databaseUrl = `file:${join(fixtureDirectory, 'legacy.db')}`
    const client = createClient({ url: databaseUrl })

    try {
      await cp(resolve(process.cwd(), 'server/database/migrations'), legacyMigrationsDirectory, { recursive: true })
      await rm(join(legacyMigrationsDirectory, '0003_mute_mole_man.sql'))
      await rm(join(legacyMigrationsDirectory, 'meta', '0003_snapshot.json'))

      const journalPath = join(legacyMigrationsDirectory, 'meta', '_journal.json')
      const journal = JSON.parse(await readFile(journalPath, 'utf8')) as { entries: Array<{ idx: number }> }
      journal.entries = journal.entries.filter(entry => entry.idx < 3)
      await writeFile(journalPath, `${JSON.stringify(journal, null, 2)}\n`)

      const database = drizzle(client)
      await migrate(database, { migrationsFolder: legacyMigrationsDirectory })

      await client.execute('CREATE TABLE IF NOT EXISTS topics (id TEXT PRIMARY KEY, title TEXT NOT NULL, main_chat_id TEXT NOT NULL, soul_content TEXT NOT NULL DEFAULT "", description TEXT, weight_mode TEXT NOT NULL DEFAULT "auto", tags TEXT, status TEXT NOT NULL DEFAULT "ready", consecutive_no_new_docs_count INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL)')
      await client.execute('CREATE TABLE IF NOT EXISTS topic_documents (id TEXT PRIMARY KEY, topic_id TEXT NOT NULL, doc_id TEXT NOT NULL, title TEXT NOT NULL, source_url TEXT, snippet TEXT, recall_count INTEGER NOT NULL DEFAULT 1, last_recalled_at INTEGER NOT NULL, score REAL, is_removed INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL)')
      await client.execute('CREATE TABLE IF NOT EXISTS message_feedbacks (id TEXT PRIMARY KEY, chat_id TEXT NOT NULL, message_id TEXT NOT NULL, is_favorite INTEGER NOT NULL DEFAULT 0, suggestion_text TEXT, created_at INTEGER NOT NULL)')

      await migrate(database, {
        migrationsFolder: resolve(process.cwd(), 'server/database/migrations')
      })

      const columns = await client.execute("PRAGMA table_info('chats')")
      expect(columns.rows.map(row => String(row.name))).toEqual(expect.arrayContaining([
        'topic_id',
        'is_branch',
        'parent_chat_id',
        'parent_message_id'
      ]))
    } finally {
      client.close()
      await rm(fixtureDirectory, {
        force: true,
        maxRetries: 5,
        recursive: true,
        retryDelay: 100
      })
    }
  }, 20_000)
})
