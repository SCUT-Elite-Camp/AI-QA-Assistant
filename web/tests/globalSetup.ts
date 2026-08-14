import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const TEMP_ROOT_ENV = 'AI_QA_VITEST_TEMP_ROOT'

/**
 * libSQL's native SQLite client can retain a Windows file handle until its
 * worker process exits, even after `client.close()`. Test workers therefore
 * allocate under one run root; Vitest deletes it only after all workers exit.
 */
export default async function setupTemporaryDatabaseRoot() {
  const temporaryRoot = await mkdtemp(join(tmpdir(), 'ai-qa-memory-test-run-'))
  process.env[TEMP_ROOT_ENV] = temporaryRoot

  return async () => {
    delete process.env[TEMP_ROOT_ENV]
    await rm(temporaryRoot, { force: true, recursive: true })
  }
}
