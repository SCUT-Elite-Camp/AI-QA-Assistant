import { drizzle } from 'drizzle-orm/libsql'
import { createClient } from '@libsql/client'

import * as schema from '../database/schema'
import { recordDbQuery } from './metrics'
import { logger } from './logger'

export { sql, eq, and, or, asc, desc, inArray } from 'drizzle-orm'

export const tables = schema

let _db: ReturnType<typeof drizzle<typeof schema>> & { $client: ReturnType<typeof createClient> }
let _schemaReady: Promise<void> | undefined
let _client: ReturnType<typeof createClient> | undefined

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
    _client = client


    const originalExecute = client.execute.bind(client)
    // 包装 execute 方法以记录耗时
    client.execute = async (...args: Parameters<typeof originalExecute>) => {
      const start = Date.now()
      try {
        const result = await originalExecute(...args)
        const duration = Date.now() - start
        recordDbQuery(duration)
        if (duration > 100) {
          const statement = args[0] as unknown
          const sql = typeof statement === 'string'
            ? statement
            : statement && typeof statement === 'object' && 'sql' in statement
              ? String(statement.sql)
              : 'unknown'
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

    // Schema creation is coordinated by the startup plugin. Starting the
    // additive reconciler here races Drizzle migrations on a fresh database:
    // it can create CP2 tables before migration 0003 and make that migration
    // fail with "table already exists".
    _schemaReady = Promise.resolve()

  }
  return _db
}

async function ensureLocalSchema(client: ReturnType<typeof createClient>) {
  await client.execute("CREATE TABLE IF NOT EXISTS topics (id TEXT PRIMARY KEY, title TEXT NOT NULL, main_chat_id TEXT NOT NULL, soul_content TEXT NOT NULL DEFAULT '', description TEXT, weight_mode TEXT NOT NULL DEFAULT 'auto', tags TEXT, status TEXT NOT NULL DEFAULT 'ready', consecutive_no_new_docs_count INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL)")

  await ensureColumns(client, 'topics', [
    ['soul_content', "ALTER TABLE topics ADD COLUMN soul_content TEXT NOT NULL DEFAULT ''"],
    ['description', 'ALTER TABLE topics ADD COLUMN description TEXT'],
    ['weight_mode', "ALTER TABLE topics ADD COLUMN weight_mode TEXT NOT NULL DEFAULT 'auto'"],
    ['tags', 'ALTER TABLE topics ADD COLUMN tags TEXT'],
    ['status', "ALTER TABLE topics ADD COLUMN status TEXT NOT NULL DEFAULT 'ready'"],
    ['consecutive_no_new_docs_count', 'ALTER TABLE topics ADD COLUMN consecutive_no_new_docs_count INTEGER NOT NULL DEFAULT 0'],
  ])

  await client.execute('CREATE TABLE IF NOT EXISTS topic_documents (id TEXT PRIMARY KEY, topic_id TEXT NOT NULL, doc_id TEXT NOT NULL, title TEXT NOT NULL, source_url TEXT, snippet TEXT, recall_count INTEGER NOT NULL DEFAULT 1, last_recalled_at INTEGER NOT NULL, score REAL, is_removed INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL)')
  await client.execute('CREATE TABLE IF NOT EXISTS message_feedbacks (id TEXT PRIMARY KEY, chat_id TEXT NOT NULL, message_id TEXT NOT NULL, is_favorite INTEGER NOT NULL DEFAULT 0, suggestion_text TEXT, created_at INTEGER NOT NULL)')
  await client.execute("CREATE TABLE IF NOT EXISTS topic_members (topic_id TEXT NOT NULL REFERENCES topics(id) ON DELETE CASCADE, user_id TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('owner','editor','viewer')), created_at INTEGER NOT NULL, PRIMARY KEY(topic_id,user_id))")
  await client.execute('CREATE TABLE IF NOT EXISTS attachment_batches (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, scope TEXT NOT NULL, chat_id TEXT REFERENCES chats(id) ON DELETE CASCADE, topic_id TEXT REFERENCES topics(id) ON DELETE CASCADE, file_count INTEGER NOT NULL DEFAULT 0, total_bytes INTEGER NOT NULL DEFAULT 0, expires_at INTEGER, created_at INTEGER NOT NULL)')
  await client.execute("CREATE TABLE IF NOT EXISTS attachments (id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES attachment_batches(id) ON DELETE CASCADE, owner_id TEXT NOT NULL, scope TEXT NOT NULL, chat_id TEXT REFERENCES chats(id) ON DELETE SET NULL, topic_id TEXT REFERENCES topics(id) ON DELETE CASCADE, filename TEXT NOT NULL, mime_type TEXT NOT NULL, size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, status TEXT NOT NULL, vision_status TEXT NOT NULL DEFAULT 'not_requested', evidence_version INTEGER NOT NULL DEFAULT 1, error_code TEXT NOT NULL DEFAULT '', expires_at INTEGER, deleted_at INTEGER, created_at INTEGER NOT NULL)")
  await client.execute('CREATE TABLE IF NOT EXISTS message_attachments (message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE, attachment_id TEXT NOT NULL REFERENCES attachments(id) ON DELETE CASCADE, evidence_version INTEGER NOT NULL, created_at INTEGER NOT NULL, PRIMARY KEY(message_id,attachment_id))')
  await client.execute("CREATE TABLE IF NOT EXISTS knowledge_bases (id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT 'My Library', scope_type TEXT NOT NULL, owner_user_id TEXT, workspace_id TEXT, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, deleted_at INTEGER, CHECK ((scope_type='personal' AND owner_user_id IS NOT NULL AND workspace_id IS NULL) OR (scope_type='enterprise' AND workspace_id IS NOT NULL)))")
  await client.execute("CREATE TABLE IF NOT EXISTS library_documents (id TEXT PRIMARY KEY, knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id), owner_user_id TEXT NOT NULL, workspace_id TEXT, source_scope TEXT NOT NULL, source_type TEXT NOT NULL DEFAULT 'upload', filename TEXT NOT NULL, display_name TEXT NOT NULL, mime_type TEXT NOT NULL, doc_type TEXT NOT NULL, active_version_id TEXT, desired_version_id TEXT, latest_version_number INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, deleted_at INTEGER)")
  await client.execute("CREATE TABLE IF NOT EXISTS document_versions (id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES library_documents(id), content_hash TEXT NOT NULL, storage_ref TEXT NOT NULL, file_size INTEGER NOT NULL, version_number INTEGER NOT NULL, status TEXT NOT NULL, error_code TEXT NOT NULL DEFAULT '', error_message TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, indexed_at INTEGER)")
  await client.execute("INSERT OR IGNORE INTO topic_members(topic_id,user_id,role,created_at) SELECT topics.id,chats.user_id,'owner',unixepoch() FROM topics JOIN chats ON chats.id=topics.main_chat_id")

  // Older local databases predate Topic/Branch and feedback support. Drizzle's
  // TypeScript schema does not migrate those existing SQLite tables by itself,
  // so add the nullable/defaulted columns before any route can insert a row.
  await ensureColumns(client, 'chats', [
    ['topic_id', 'ALTER TABLE chats ADD COLUMN topic_id TEXT REFERENCES topics(id) ON DELETE SET NULL'],
    ['is_branch', 'ALTER TABLE chats ADD COLUMN is_branch INTEGER NOT NULL DEFAULT 0'],
    ['parent_chat_id', 'ALTER TABLE chats ADD COLUMN parent_chat_id TEXT'],
    ['parent_message_id', 'ALTER TABLE chats ADD COLUMN parent_message_id TEXT'],
  ])
  await ensureColumns(client, 'messages', [
    ['is_favorite', 'ALTER TABLE messages ADD COLUMN is_favorite INTEGER NOT NULL DEFAULT 0'],
    ['suggestion_text', 'ALTER TABLE messages ADD COLUMN suggestion_text TEXT'],
  ])
  await ensureColumns(client, 'library_documents', [
    ['desired_version_id', 'ALTER TABLE library_documents ADD COLUMN desired_version_id TEXT'],
    ['latest_version_number', 'ALTER TABLE library_documents ADD COLUMN latest_version_number INTEGER NOT NULL DEFAULT 0'],
  ])
  await ensureColumns(client, 'document_versions', [
    ['version_number', 'ALTER TABLE document_versions ADD COLUMN version_number INTEGER NOT NULL DEFAULT 0'],
  ])
  await client.execute(`WITH ranked AS (
    SELECT id, ROW_NUMBER() OVER (PARTITION BY document_id ORDER BY created_at,id) AS number
    FROM document_versions
  ) UPDATE document_versions SET version_number=(
    SELECT number FROM ranked WHERE ranked.id=document_versions.id
  ) WHERE version_number=0`)
  await client.execute(`UPDATE library_documents SET latest_version_number=COALESCE((
    SELECT MAX(version_number) FROM document_versions WHERE document_id=library_documents.id
  ),0) WHERE latest_version_number=0`)

  await client.execute('CREATE INDEX IF NOT EXISTS chats_topic_id_idx ON chats(topic_id)')
  await client.execute('CREATE INDEX IF NOT EXISTS topic_docs_topic_id_idx ON topic_documents(topic_id)')
  await client.execute('CREATE UNIQUE INDEX IF NOT EXISTS topic_doc_idx ON topic_documents(topic_id, doc_id)')
  await client.execute('CREATE INDEX IF NOT EXISTS msg_feedbacks_chat_id_idx ON message_feedbacks(chat_id)')
  await client.execute('CREATE INDEX IF NOT EXISTS msg_feedbacks_msg_id_idx ON message_feedbacks(message_id)')
  await client.execute('CREATE INDEX IF NOT EXISTS topic_members_user_idx ON topic_members(user_id)')
  await client.execute('CREATE INDEX IF NOT EXISTS attachments_owner_idx ON attachments(owner_id)')
  await client.execute('CREATE INDEX IF NOT EXISTS attachments_topic_idx ON attachments(topic_id)')
  await client.execute('CREATE INDEX IF NOT EXISTS attachments_expiry_idx ON attachments(expires_at)')
  await client.execute('CREATE INDEX IF NOT EXISTS message_attachments_attachment_idx ON message_attachments(attachment_id)')
  await client.execute('CREATE INDEX IF NOT EXISTS knowledge_bases_owner_idx ON knowledge_bases(owner_user_id,scope_type)')
  await client.execute('CREATE INDEX IF NOT EXISTS library_documents_owner_idx ON library_documents(owner_user_id,deleted_at)')
  await client.execute('CREATE INDEX IF NOT EXISTS library_documents_kb_idx ON library_documents(knowledge_base_id,deleted_at)')
  await client.execute('CREATE INDEX IF NOT EXISTS document_versions_document_idx ON document_versions(document_id,created_at)')
  await client.execute('CREATE UNIQUE INDEX IF NOT EXISTS document_versions_identity_idx ON document_versions(document_id,content_hash)')
  await client.execute('CREATE UNIQUE INDEX IF NOT EXISTS document_versions_number_idx ON document_versions(document_id,version_number)')
}

async function ensureColumns(
  client: ReturnType<typeof createClient>,
  table: string,
  columns: readonly (readonly [string, string])[],
) {
  const tableInfo = await client.execute(`PRAGMA table_info(${table})`)
  if (tableInfo.rows.length === 0) {
    return
  }
  const existingColumns = new Set(
    tableInfo.rows.map(row => String(row.name))
  )
  for (const [column, statement] of columns) {
    if (!existingColumns.has(column)) {
      await client.execute(statement)
      existingColumns.add(column)
    }
  }
}

export async function ensureDrizzleReady() {
  useDrizzle()
  if (!_client) {
    throw new Error('Database client is not initialized')
  }
  _schemaReady = ensureLocalSchema(_client)
  await _schemaReady
}

export async function reconcileDrizzleSchema() {
  useDrizzle()
  await _schemaReady
  if (!_client) {
    throw new Error('Database client is not initialized')
  }
  _schemaReady = ensureLocalSchema(_client)
  await _schemaReady
}


export type Chat = typeof schema.chats.$inferSelect
export type Message = typeof schema.messages.$inferSelect
export type Vote = typeof schema.votes.$inferSelect
