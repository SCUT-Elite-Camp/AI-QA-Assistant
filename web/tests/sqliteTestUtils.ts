import { rmSync } from 'node:fs'

export function removeTemporaryDatabaseDirectory(directory: string) {
  try {
    rmSync(directory, {
      recursive: true,
      force: true,
      maxRetries: 1,
      retryDelay: 25,
    })
  } catch (error) {
    // GitHub's Windows runner can retain a libSQL file handle briefly after
    // client.close(). Only tolerate locks while removing an isolated test
    // directory; database assertions and all other filesystem errors remain
    // failures.
    const code = (error as NodeJS.ErrnoException).code
    if (code !== 'EPERM' && code !== 'EBUSY') throw error
  }
}
