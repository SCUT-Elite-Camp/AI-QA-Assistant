import { describe, expect, it } from 'vitest'
import { topicCapabilities } from '../shared/utils/topicCapabilities'

describe('Topic chat capabilities', () => {
  it('allows viewers to ask questions but not upload or edit', () => {
    expect(topicCapabilities(true, 'viewer')).toEqual({
      canChat: true, canUploadAttachments: false, canEditTopic: false,
    })
  })

  it('allows editors and owners to upload and edit', () => {
    for (const role of ['editor', 'owner'] as const) {
      expect(topicCapabilities(false, role)).toEqual({
        canChat: true, canUploadAttachments: true, canEditTopic: true,
      })
    }
  })

  it('keeps non-Topic private chats owner-only', () => {
    expect(topicCapabilities(false, null).canChat).toBe(false)
    expect(topicCapabilities(true, null).canUploadAttachments).toBe(true)
  })
})
