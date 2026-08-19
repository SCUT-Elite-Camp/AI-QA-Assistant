import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { createClient } from '@libsql/client'
import { describe, expect, it } from 'vitest'


describe('library version order migration', () => {
  it('backfills deterministic version numbers and the document counter', async () => {
    const client = createClient({ url: ':memory:' })
    await client.execute('CREATE TABLE library_documents (id TEXT PRIMARY KEY, active_version_id TEXT)')
    await client.execute('CREATE TABLE document_versions (id TEXT PRIMARY KEY, document_id TEXT NOT NULL, created_at INTEGER NOT NULL)')
    await client.execute("INSERT INTO library_documents(id,active_version_id) VALUES('doc-a','ver-2')")
    await client.execute("INSERT INTO document_versions VALUES('ver-2','doc-a',20),('ver-1','doc-a',10)")
    const migrationPath = fileURLToPath(new URL('../server/database/migrations/0005_library_version_order.sql', import.meta.url))
    const statements = readFileSync(migrationPath, 'utf8').split('--> statement-breakpoint').map(item => item.trim()).filter(Boolean)
    for (const statement of statements) await client.execute(statement)

    const versions = await client.execute('SELECT id,version_number FROM document_versions ORDER BY version_number')
    expect(versions.rows.map(row => [row.id, Number(row.version_number)])).toEqual([
      ['ver-1', 1], ['ver-2', 2],
    ])
    const document = await client.execute("SELECT latest_version_number,desired_version_id FROM library_documents WHERE id='doc-a'")
    expect(Number(document.rows[0].latest_version_number)).toBe(2)
    expect(document.rows[0].desired_version_id).toBe('ver-2')
    client.close()
  })
})
