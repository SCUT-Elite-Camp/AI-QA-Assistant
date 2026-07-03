const UNKNOWN_ERROR_MESSAGE = 'The service is temporarily unavailable. Please try again later.'

export const ERROR_MESSAGES: Record<string, string> = {
  success: '',
  invalid_query: 'Please enter a valid question.',
  no_relevant_context: 'The knowledge base does not have sufficient information to answer this question.',
  retrieval_error: 'The retrieval service is temporarily unavailable. Please try again later.',
  llm_error: 'The model service is temporarily unavailable. Please try again later.',
  network_error: 'Network connection error. Please check if the BFF service is running.',
  timeout_error: 'Request timed out. Please try again later.',
  stream_error: 'Generation interrupted. Please try again later.',
  unknown_error: UNKNOWN_ERROR_MESSAGE,
}

export function getErrorMessage(status?: string, fallbackMessage?: string): string {
  const normalizedFallback = typeof fallbackMessage === 'string' ? fallbackMessage.trim() : ''

  if (normalizedFallback) {
    return normalizedFallback
  }

  if (status && Object.prototype.hasOwnProperty.call(ERROR_MESSAGES, status)) {
    return ERROR_MESSAGES[status] ?? UNKNOWN_ERROR_MESSAGE
  }

  return UNKNOWN_ERROR_MESSAGE
}
