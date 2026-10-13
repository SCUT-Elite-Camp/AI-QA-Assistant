/** Public failures are selected from a fixed vocabulary; provider bodies stay server-side. */
export class ChatModelFailure extends Error {
  constructor(readonly code: 'model_daily_quota' | 'model_rate_limit' | 'model_unavailable') {
    super(code)
    this.name = 'ChatModelFailure'
  }
}

export function classifyModelFailure(message: unknown): ChatModelFailure | undefined {
  if (typeof message !== 'string' || !/\bLLM\b|free-models-per-(?:day|min)/i.test(message)) return
  if (/free-models-per-day/i.test(message)) return new ChatModelFailure('model_daily_quota')
  if (/\b429\b|free-models-per-min/i.test(message)) return new ChatModelFailure('model_rate_limit')
  return new ChatModelFailure('model_unavailable')
}

export function publicChatFailure(error: unknown) {
  if (error instanceof ChatModelFailure) {
    const messages = {
      model_daily_quota: 'The model’s daily free quota has been reached. Try again after it resets or use another configured model.',
      model_rate_limit: 'The model is receiving too many requests. Please wait a moment and try again.',
      model_unavailable: 'The model service is unavailable. Please try again shortly.',
    }
    return { status: error.code, message: messages[error.code] }
  }
  if (error instanceof Error && error.message === 'agent_unavailable') {
    return { status: 'service_unavailable', message: 'The answer service is unavailable. No answer is being released. Please try again shortly.' }
  }
  return { status: 'answer_failed', message: 'The answer could not pass identity, source access, version, or persistence checks. No answer is being released. Please retry.' }
}
