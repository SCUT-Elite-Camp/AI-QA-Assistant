export const ERROR_MESSAGES: Record<string, string> = {
  success: '',
  invalid_query: 'Please enter a valid question',
  no_relevant_context: 'Not enough information in the knowledge base to answer this question',
  retrieval_error: 'Retrieval service is temporarily unavailable, please try again later',
  llm_error: 'Model service is temporarily unavailable, please try again later',
  network_error: 'Network connection error, please check if the service is running',
  timeout_error: 'Request timed out, please try again later',
  stream_error: 'Generation interrupted, please try again later',
  unknown_error: 'Service is temporarily unavailable, please try again later',
}

export function getErrorMessage(status?: string, fallbackMessage?: string): string {
  const normalizedFallback = typeof fallbackMessage === 'string' ? fallbackMessage.trim() : ''

  if (normalizedFallback) {
    return normalizedFallback
  }

  if (status && Object.prototype.hasOwnProperty.call(ERROR_MESSAGES, status)) {
    return ERROR_MESSAGES[status]
  }

  return ERROR_MESSAGES.unknown_error
}
