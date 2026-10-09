import { describe, expect, it } from 'vitest'
import { desiredActivationMode, resolveUploadedHash } from '../server/utils/libraryVersionService'


describe('personal library version decisions', () => {
  it('treats only the active hash as unchanged', () => {
    expect(resolveUploadedHash('hash-a', 'hash-a', 'READY')).toBe('unchanged')
    expect(resolveUploadedHash('hash-b', 'hash-a', 'READY')).toBe('reactivate')
  })

  it('retries a matching failed historical version', () => {
    expect(resolveUploadedHash('hash-b', 'hash-a', 'FAILED')).toBe('retry')
  })

  it('does not activate an older version that is no longer desired', () => {
    expect(desiredActivationMode('ver-3', {
      id: 'ver-2', status: 'READY', versionNumber: 2,
    }, { versionNumber: 3 })).toEqual({ allowed: false, explicit: false })
  })

  it('allows an explicit A-B-A historical reactivation', () => {
    expect(desiredActivationMode('ver-a', {
      id: 'ver-a', status: 'READY', versionNumber: 1,
    }, { versionNumber: 2 })).toEqual({ allowed: true, explicit: true })
  })
})
