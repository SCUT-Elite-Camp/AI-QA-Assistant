import { describe, expect, it } from 'vitest'
import { mapLibraryStatus } from '../server/utils/library'

describe('personal library ingestion status', () => {
  it.each([
    ['scanning', 'UPLOADED'],
    ['parsing', 'PARSING'],
    ['chunking', 'CHUNKING'],
    ['embedding', 'EMBEDDING'],
    ['indexing', 'INDEXING'],
    ['ready', 'READY'],
    ['needs_review', 'READY'],
    ['failed', 'FAILED'],
    ['quarantined', 'FAILED'],
  ])('maps %s to %s', (remote, expected) => {
    expect(mapLibraryStatus(remote)).toBe(expected)
  })
})
