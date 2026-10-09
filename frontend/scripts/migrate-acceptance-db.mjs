import { createClient } from '@libsql/client'
import { drizzle } from 'drizzle-orm/libsql'
import { migrate } from 'drizzle-orm/libsql/migrator'

const url = process.env.TURSO_DATABASE_URL
if (!url?.startsWith('file:')) throw new Error('isolated_local_database_required')
const client = createClient({ url })
try {
  await migrate(drizzle(client), { migrationsFolder: 'server/database/migrations' })
  console.log('acceptance_schema_migrated')
} finally { client.close() }
