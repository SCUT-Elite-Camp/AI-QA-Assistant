import { describe, expect, it } from 'vitest'
import { ensureOwnerContinuity, topicRoleAtLeast } from '../server/utils/attachmentAuth'
import { attachmentHasExpired } from '../server/utils/attachmentAccess'

describe('attachment topic authorization rules', () => {
  it('enforces the owner/editor/viewer role ordering', () => {
    expect(topicRoleAtLeast('owner', 'editor')).toBe(true)
    expect(topicRoleAtLeast('editor', 'viewer')).toBe(true)
    expect(topicRoleAtLeast('viewer', 'editor')).toBe(false)
  })

  it('expires only temporary draft/chat attachments', () => {
    const past = new Date('2026-08-12T00:00:00Z')
    const now = new Date('2026-08-13T00:00:00Z')
    expect(attachmentHasExpired({ scope: 'chat', expiresAt: past }, now)).toBe(true)
    expect(attachmentHasExpired({ scope: 'draft', expiresAt: past }, now)).toBe(true)
    expect(attachmentHasExpired({ scope: 'topic', expiresAt: past }, now)).toBe(false)
    expect(attachmentHasExpired({ scope: 'chat', expiresAt: null }, now)).toBe(false)
  })

  it('does not permit deleting or demoting the final owner', () => {
    expect(() => ensureOwnerContinuity('owner', undefined, 1)).toThrowError(/last_owner_required/)
    expect(() => ensureOwnerContinuity('owner', 'editor', 1)).toThrowError(/last_owner_required/)
    expect(() => ensureOwnerContinuity('owner', 'editor', 2)).not.toThrow()
    expect(() => ensureOwnerContinuity('editor', undefined, 1)).not.toThrow()
  })
})
