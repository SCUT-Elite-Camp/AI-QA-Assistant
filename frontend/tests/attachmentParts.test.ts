import { describe, expect, it } from 'vitest'
import { extractAttachmentSelection, mergeSafeAttachmentParts } from '../shared/utils/attachmentParts'

describe('attachment message parts', () => {
  it('retains low-confidence review acceptance through edit and regeneration', () => {
    const parts = mergeSafeAttachmentParts(
      [{ type: 'text', text: '分析附件' }],
      [{ id: 'att_review', filename: '截图.png', mimeType: 'image/png', status: 'needs_review' }],
      new Set(['att_review']),
    )
    expect(extractAttachmentSelection(parts)).toEqual({
      attachmentIds: ['att_review'],
      acceptedNeedsReviewIds: ['att_review'],
    })
  })

  it('replaces untrusted client attachment parts with server-owned metadata', () => {
    const parts = mergeSafeAttachmentParts(
      [
        { type: 'text', text: '问题' },
        { type: 'data-attachment', data: { attachment_id: 'att_forged', filename: 'secret.txt' } },
      ],
      [{ id: 'att_allowed', filename: '制度.pdf', mimeType: 'application/pdf', status: 'ready' }],
      new Set(),
    )
    expect(parts).toHaveLength(2)
    expect((parts[1] as any).data).toEqual({
      attachment_id: 'att_allowed',
      filename: '制度.pdf',
      mime_type: 'application/pdf',
      status: 'ready',
      accepted_review: false,
    })
  })

  it('deduplicates and bounds attachment ids from metadata and parts', () => {
    const result = extractAttachmentSelection(
      [{ type: 'data-attachment', data: { attachment_id: 'att_one', accepted_review: true } }],
      { attachmentIds: ['att_one', 'invalid'], acceptedNeedsReviewIds: ['att_one'] },
    )
    expect(result).toEqual({ attachmentIds: ['att_one'], acceptedNeedsReviewIds: ['att_one'] })
  })
})
