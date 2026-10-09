import { describe, expect, it } from 'vitest'

import { isPersonalLibraryRouteEnabled } from '../server/utils/personalLibraryFlags'

describe('personal library feature flags', () => {
  it('keeps attachment and library routes disabled by default', () => {
    expect(isPersonalLibraryRouteEnabled('attachments', {})).toBe(false)
    expect(isPersonalLibraryRouteEnabled('library', {})).toBe(false)
  })

  it('requires both flags for personal library routes', () => {
    expect(isPersonalLibraryRouteEnabled('attachments', { ATTACHMENTS_ENABLED: 'true' })).toBe(true)
    expect(isPersonalLibraryRouteEnabled('library', { PERSONAL_LIBRARY_ENABLED: 'true' })).toBe(false)
    expect(isPersonalLibraryRouteEnabled('library', {
      ATTACHMENTS_ENABLED: 'true',
      PERSONAL_LIBRARY_ENABLED: 'true'
    })).toBe(true)
  })
})
