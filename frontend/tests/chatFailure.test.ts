import { describe, expect, it } from 'vitest'
import { classifyModelFailure, publicChatFailure } from '../server/utils/chatFailure'

describe('safe answer failures', () => {
  it('distinguishes daily quota, short limits and unavailable models', () => {
    expect(classifyModelFailure('LLM API 429 free-models-per-day')?.code).toBe('model_daily_quota')
    expect(classifyModelFailure('LLM API 429')?.code).toBe('model_rate_limit')
    expect(classifyModelFailure('LLM API 503')?.code).toBe('model_unavailable')
  })
  it('keeps source errors fail closed and never forwards raw provider details', () => {
    expect(classifyModelFailure('Confluence read returned 429')).toBeUndefined()
    expect(publicChatFailure(new Error('private source body')).message).not.toContain('private source body')
    expect(publicChatFailure(classifyModelFailure('LLM API 503 secret-provider-details')).message).not.toContain('secret-provider-details')
  })
})
