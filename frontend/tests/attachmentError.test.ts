import { describe, expect, it } from 'vitest'
import { attachmentErrorCode, attachmentErrorMessage } from '../src/utils/attachmentError'

describe('attachment errors', () => {
  it('reads Nitro and parser errors without exposing raw internal messages', () => {
    expect(attachmentErrorCode({ data: { code: 'file_too_large' } })).toBe('file_too_large')
    expect(attachmentErrorCode({ detail: { code: 'parse_timeout' } })).toBe('parse_timeout')
    expect(attachmentErrorCode({ message: 'attachments_unavailable' })).toBe('attachments_unavailable')
    expect(attachmentErrorCode({ message: 'internal file path or credential' })).toBe('upload_failed')
    expect(attachmentErrorMessage('parse_timeout')).toContain('timed out')
    expect(attachmentErrorMessage('internal file path')).not.toContain('internal file path')
  })
})
