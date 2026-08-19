import { createClient } from '@libsql/client'
import { drizzle } from 'drizzle-orm/libsql'
import { migrate } from 'drizzle-orm/libsql/migrator'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import * as schema from '../server/database/schema'
import { removeTemporaryDatabaseDirectory } from './sqliteTestUtils'
import {
  createDocumentWithInitialVersion,
  createLibraryVersion,
  insertInitialLibraryDocument,
  insertInitialLibraryVersion,
  updateInitialLibraryPointers,
} from '../server/utils/libraryVersionService'

type TestDb = ReturnType<typeof drizzle<typeof schema>>

const clients: ReturnType<typeof createClient>[] = []
const databaseDirectories: string[] = []

async function database() {
  const baseDirectory = process.platform === 'win32' ? 'C:\\Users\\Public' : tmpdir()
  const directory = mkdtempSync(join(baseDirectory, 'aiqa-vitest-library-'))
  databaseDirectories.push(directory)
  const client = createClient({ url: `file:${join(directory, 'test.sqlite3')}` })
  clients.push(client)
  const db = drizzle(client, { schema })
  await client.execute('PRAGMA busy_timeout=5000')
  await migrate(db, { migrationsFolder: 'server/database/migrations' })
  await db.insert(schema.knowledgeBases).values({
    id: 'kb-a', name: 'My Library', scopeType: 'personal', ownerUserId: 'user-a',
    createdAt: new Date(), updatedAt: new Date(),
  })
  return db
}

function initialRows(suffix = '') {
  const documentId = `doc-a${suffix}`
  const versionId = `ver-a${suffix}`
  return {
    document: {
      id: documentId,
      knowledgeBaseId: 'kb-a',
      ownerUserId: 'user-a',
      sourceScope: 'personal' as const,
      sourceType: 'upload',
      filename: 'report.md',
      displayName: 'report.md',
      mimeType: 'text/markdown',
      docType: 'md',
      createdAt: new Date(),
      updatedAt: new Date(),
    },
    version: {
      id: versionId,
      documentId,
      contentHash: `hash${suffix}`,
      storageRef: versionId,
      fileSize: 42,
      status: 'UPLOADED' as const,
      createdAt: new Date(),
      updatedAt: new Date(),
    },
  }
}

async function visibleDocumentCount(db: TestDb) {
  const rows = await db.select().from(schema.libraryDocuments)
  return rows.filter(row => row.sourceScope === 'personal' && row.deletedAt === null).length
}

afterEach(async () => {
  while (clients.length) await clients.pop()!.close()
  while (databaseDirectories.length) {
    removeTemporaryDatabaseDirectory(databaseDirectories.pop()!)
  }
})

describe('personal library document/version transactions', () => {
  it('atomically creates a document and its initial desired version', async () => {
    const db = await database()
    const rows = initialRows()
    await createDocumentWithInitialVersion(rows.document, rows.version, db)

    const documents = await db.select().from(schema.libraryDocuments)
    const versions = await db.select().from(schema.documentVersions)
    expect(documents).toHaveLength(1)
    expect(versions).toHaveLength(1)
    expect(documents[0]).toMatchObject({
      latestVersionNumber: 1,
      desiredVersionId: rows.version.id,
      activeVersionId: null,
    })
    expect(versions[0].versionNumber).toBe(1)
  })

  it.each([
    'after document insert',
    'after version insert',
    'before pointer update',
    'before commit',
  ])('rolls back without a visible orphan on failure %s', async (failurePoint) => {
    const db = await database()
    const rows = initialRows(`-${failurePoint.replaceAll(' ', '-')}`)

    await expect(db.transaction(async (tx) => {
      await insertInitialLibraryDocument(tx, rows.document)
      if (failurePoint === 'after document insert') throw new Error('injected_failure')
      await insertInitialLibraryVersion(tx, rows.version)
      if (failurePoint === 'after version insert') throw new Error('injected_failure')
      if (failurePoint === 'before pointer update') throw new Error('injected_failure')
      await updateInitialLibraryPointers(tx, rows.document.id, rows.version.id)
      if (failurePoint === 'before commit') throw new Error('injected_failure')
    })).rejects.toThrow('injected_failure')

    expect(await visibleDocumentCount(db)).toBe(0)
    expect(await db.select().from(schema.documentVersions)).toHaveLength(0)
  })

  it('allocates unique monotonically increasing version numbers concurrently', async () => {
    const db = await database()
    const initial = initialRows()
    await createDocumentWithInitialVersion(initial.document, initial.version, db)

    const results = await Promise.all(Array.from({ length: 8 }, async (_, index) => {
      const id = `ver-${index + 2}`
      return createLibraryVersion(initial.document.id, {
        id,
        documentId: initial.document.id,
        contentHash: `hash-${index + 2}`,
        storageRef: id,
        fileSize: 50 + index,
        status: 'UPLOADED',
        createdAt: new Date(),
        updatedAt: new Date(),
      }, undefined, db)
    }))

    expect(new Set(results).size).toBe(8)
    const versions = await db.select().from(schema.documentVersions)
    expect(versions.map(row => row.versionNumber).sort((a, b) => a - b))
      .toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9])
  })

  it('deduplicates concurrent uploads of the same content hash', async () => {
    const db = await database()
    const initial = initialRows()
    await createDocumentWithInitialVersion(initial.document, initial.version, db)
    const create = (id: string) => createLibraryVersion(initial.document.id, {
      id,
      documentId: initial.document.id,
      contentHash: 'same-new-hash',
      storageRef: id,
      fileSize: 50,
      status: 'UPLOADED',
      createdAt: new Date(),
      updatedAt: new Date(),
    }, undefined, db)

    const outcomes = await Promise.allSettled([create('ver-race-a'), create('ver-race-b')])
    expect(outcomes.filter(result => result.status === 'fulfilled')).toHaveLength(1)
    expect(outcomes.filter(result => result.status === 'rejected')).toHaveLength(1)
    const versions = await db.select().from(schema.documentVersions)
    expect(versions.filter(row => row.contentHash === 'same-new-hash')).toHaveLength(1)
  })
})
