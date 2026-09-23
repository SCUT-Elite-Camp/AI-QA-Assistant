import { describe, expect, it } from 'vitest'
import { createAgentStreamError, getAgentFailureMessage } from '../server/utils/agentResponse'

describe('agent response stream handling', () => {
  it.each(['success', 'clarification_required'])('accepts %s responses', (status) => {
    expect(getAgentFailureMessage({ status })).toBeNull()
  })

  it('turns an Agent llm_error into a terminal UI stream error', () => {
    const message = getAgentFailureMessage({
      status: 'llm_error',
      message: '模型服务暂时不可用，请稍后重试。',
    })

    expect(message).toBe('模型服务暂时不可用，请稍后重试。')
    expect(createAgentStreamError(message)).toEqual({
      type: 'error',
      errorText: '模型服务暂时不可用，请稍后重试。',
    })
  })

  it('does not expose a non-string error object', () => {
    expect(createAgentStreamError({ secret: 'hidden' })).toEqual({
      type: 'error',
      errorText: 'Failed to retrieve answer from Agent Layer',
    })
  })
})
