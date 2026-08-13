import { createClient } from '@libsql/client'
import { expect, it, test } from 'vitest'

it('starts each suite with an empty migrated database', async () => {
  const client = createClient({ url: process.env.TURSO_DATABASE_URL! })
  try {
    const result = await client.execute('SELECT COUNT(*) AS count FROM users')
    expect(Number(result.rows[0]?.count)).toBe(0)
  } finally {
    client.close()
  }
})

test.todo('Unit 03 will cover the MemorySnapshot and MemoryFact repository')
