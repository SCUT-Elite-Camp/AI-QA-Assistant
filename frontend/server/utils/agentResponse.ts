export interface AgentResponseStatus {
  status?: unknown
  message?: unknown
}

const SUCCESS_STATUSES = new Set(['success', 'clarification_required'])

export function getAgentFailureMessage(payload: AgentResponseStatus): string | null {
  if (typeof payload.status === 'string' && SUCCESS_STATUSES.has(payload.status)) return null
  if (typeof payload.message === 'string' && payload.message.trim()) return payload.message.trim()
  return 'RAG retrieval error from Agent layer'
}

export function createAgentStreamError(error: unknown) {
  const message = error instanceof Error
    ? error.message
    : typeof error === 'string'
      ? error
      : 'Failed to retrieve answer from Agent Layer'
  return {
    type: 'error' as const,
    errorText: message,
  }
}
