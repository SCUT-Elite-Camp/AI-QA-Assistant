import { createClient } from '@libsql/client'
import { drizzle } from 'drizzle-orm/libsql'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import * as schema from '../server/database/schema'
import {
  getPersonalLibraryDocument,
  personalLibraryDocumentPredicate,
} from '../server/utils/library'

async function authorizationDatabase() {
  const client = createClient({ url: 'file::memory:' })
  await client.execute(`CREATE TABLE library_documents (
    id TEXT PRIMARY KEY,
    knowledge_base_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    workspace_id TEXT,
    source_scope TEXT NOT NULL,
    source_type TEXT NOT NULL,
    filename TEXT NOT NULL,
    display_name TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    active_version_id TEXT,
    desired_version_id TEXT,
    latest_version_number INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    deleted_at INTEGER
  )`)
  const db = drizzle(client, { schema })
  const base = {
    sourceType: 'upload', filename: 'report.md', displayName: 'report.md',
    mimeType: 'text/markdown', docType: 'md', latestVersionNumber: 1,
    createdAt: new Date(), updatedAt: new Date(),
  }
  await db.insert(schema.libraryDocuments).values([
    { ...base, id: 'allowed', ownerUserId: 'owner-a', knowledgeBaseId: 'kb-a', sourceScope: 'personal' },
    { ...base, id: 'wrong-owner', ownerUserId: 'owner-b', knowledgeBaseId: 'kb-a', sourceScope: 'personal' },
    { ...base, id: 'wrong-kb', ownerUserId: 'owner-a', knowledgeBaseId: 'kb-b', sourceScope: 'personal' },
    { ...base, id: 'enterprise', ownerUserId: 'owner-a', knowledgeBaseId: 'kb-a', sourceScope: 'enterprise' },
    { ...base, id: 'deleted', ownerUserId: 'owner-a', knowledgeBaseId: 'kb-a', sourceScope: 'personal', deletedAt: new Date() },
  ])
  return { client, db }
}

describe('personal library authorization predicate', () => {
  it('requires owner, resolved KB, personal scope, and visible state together', async () => {
    const { client, db } = await authorizationDatabase()
    try {
      const visible = await db.select().from(schema.libraryDocuments)
        .where(personalLibraryDocumentPredicate('owner-a', 'kb-a'))
      expect(visible.map(row => row.id)).toEqual(['allowed'])

      await expect(getPersonalLibraryDocument('owner-a', 'kb-a', 'allowed', db))
        .resolves.toMatchObject({ id: 'allowed' })
      for (const id of ['wrong-owner', 'wrong-kb', 'enterprise', 'deleted']) {
        await expect(getPersonalLibraryDocument('owner-a', 'kb-a', id, db))
          .resolves.toBeUndefined()
      }
    } finally {
      client.close()
    }
  })

  it('keeps every Personal Library endpoint on the shared authorization path', () => {
    const routeRoot = new URL('../server/routes/api/library/files/', import.meta.url)
    const routes: Record<string, string> = {
      'index.get.ts': 'personalLibraryDocumentPredicate',
      'index.post.ts': 'getPersonalLibraryDocument',
      '[document_id].get.ts': 'requireLibraryDocument',
      '[document_id].delete.ts': 'requireLibraryDocument',
      '[document_id]/content.get.ts': 'requireLibraryDocument',
      '[document_id]/reindex.post.ts': 'requireLibraryDocument',
      '[document_id]/status.get.ts': 'requireLibraryDocument',
      '[document_id]/versions/index.get.ts': 'requireLibraryDocument',
      '[document_id]/versions/[version_id]/activate.post.ts': 'requireLibraryDocument',
    }
    for (const [relativePath, helper] of Object.entries(routes)) {
      const source = readFileSync(fileURLToPath(new URL(relativePath, routeRoot)), 'utf8')
      expect(source, relativePath).toContain(helper)
    }
  })
})
