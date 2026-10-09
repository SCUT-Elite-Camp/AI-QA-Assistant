import { describe, expect, it } from 'vitest'
import { resolveRuntimeDatabaseUrl } from '../../server/utils/drizzle'

describe('runtime database URL', () => {
  it('uses the documented local URL only in development', () => {
    expect(resolveRuntimeDatabaseUrl({ NODE_ENV: 'development' }, 'D:/project/AI-QA-Assistant/web'))
      .toBe('file:D:\\project\\AI-QA-Assistant\\web\\.data\\sqlite.db')
  })

  it('uses an explicit URL in every environment', () => {
    expect(resolveRuntimeDatabaseUrl({ TURSO_DATABASE_URL: 'file:custom.db' }))
      .toBe('file:custom.db')
  })

  it('rejects an implicit database URL outside development', () => {
    expect(() => resolveRuntimeDatabaseUrl({ NODE_ENV: 'production' }))
      .toThrow('TURSO_DATABASE_URL must be configured outside development')
  })
})
