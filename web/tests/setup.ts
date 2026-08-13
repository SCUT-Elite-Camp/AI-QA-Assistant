import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { afterAll, beforeAll } from 'vitest'

let temporaryDirectory: string | undefined
let originalDatabaseUrl: string | undefined
let originalAuthToken: string | undefined

beforeAll(async () => {
  temporaryDirectory = await mkdtemp(join(tmpdir(), 'ai-qa-memory-test-'))
  originalDatabaseUrl = process.env.TURSO_DATABASE_URL
  originalAuthToken = process.env.TURSO_AUTH_TOKEN

  const databaseUrl = `file:${join(temporaryDirectory, 'memory-test.db')}`
  process.env.TURSO_DATABASE_URL = databaseUrl
  delete process.env.TURSO_AUTH_TOKEN

  // Import only after the temporary database URL is configured so no suite
  // can reuse a process-level connection from another environment.
  const [{ createClient }, { drizzle }, { migrate }, { resetDrizzleForTests }] = await Promise.all([
    import('@libsql/client'),
    import('drizzle-orm/libsql'),
    import('drizzle-orm/libsql/migrator'),
    import('../server/utils/drizzle')
  ])

  resetDrizzleForTests()
  const client = createClient({ url: databaseUrl })
  const database = drizzle(client)

  try {
    await migrate(database, {
      migrationsFolder: resolve(process.cwd(), 'server/database/migrations')
    })
  } finally {
    client.close()
  }
})

afterAll(async () => {
  const { resetDrizzleForTests } = await import('../server/utils/drizzle')
  resetDrizzleForTests()

  if (originalDatabaseUrl === undefined) {
    delete process.env.TURSO_DATABASE_URL
  } else {
    process.env.TURSO_DATABASE_URL = originalDatabaseUrl
  }

  if (originalAuthToken === undefined) {
    delete process.env.TURSO_AUTH_TOKEN
  } else {
    process.env.TURSO_AUTH_TOKEN = originalAuthToken
  }

  if (temporaryDirectory) {
    await rm(temporaryDirectory, {
      force: true,
      maxRetries: 5,
      recursive: true,
      retryDelay: 100
    })
  }
})
