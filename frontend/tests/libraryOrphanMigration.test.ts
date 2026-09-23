import { createClient } from '@libsql/client'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

describe('personal library orphan repair migration', () => {
  it('soft-deletes visible zero-version personal documents only', async () => {
    const client = createClient({ url: 'file::memory:' })
    try {
      await client.execute(`CREATE TABLE library_documents (
        id TEXT PRIMARY KEY,
        source_scope TEXT NOT NULL,
        active_version_id TEXT,
        desired_version_id TEXT,
        updated_at INTEGER NOT NULL,
        deleted_at INTEGER
      )`)
      await client.execute(`CREATE TABLE document_versions (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL
      )`)
      await client.execute(`INSERT INTO library_documents VALUES
        ('personal-orphan','personal','missing','missing',1,NULL),
        ('personal-valid','personal','ver-valid','ver-valid',1,NULL),
        ('enterprise-orphan','enterprise',NULL,NULL,1,NULL),
        ('already-deleted','personal',NULL,NULL,1,9)`)
      await client.execute("INSERT INTO document_versions VALUES('ver-valid','personal-valid')")

      const migrationPath = fileURLToPath(new URL(
        '../server/database/migrations/0006_library_orphan_repair.sql',
        import.meta.url,
      ))
      await client.execute(readFileSync(migrationPath, 'utf8'))

      const rows = await client.execute(
        'SELECT id,active_version_id,desired_version_id,deleted_at FROM library_documents ORDER BY id',
      )
      const byId = new Map(rows.rows.map(row => [String(row.id), row]))
      expect(byId.get('personal-orphan')!.deleted_at).not.toBeNull()
      expect(byId.get('personal-orphan')!.active_version_id).toBeNull()
      expect(byId.get('personal-orphan')!.desired_version_id).toBeNull()
      expect(byId.get('personal-valid')!.deleted_at).toBeNull()
      expect(byId.get('enterprise-orphan')!.deleted_at).toBeNull()
      expect(Number(byId.get('already-deleted')!.deleted_at)).toBe(9)
    } finally {
      client.close()
    }
  })
})
