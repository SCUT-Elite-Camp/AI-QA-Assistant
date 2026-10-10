/** Retry only a missing, client-only final response from a failed stream. */
export function canRetryMissingResponse(
  error: { statusCode?: number, status?: number } | null | undefined,
  status: string,
  message: { id: string, role: string },
  lastMessageId: string | undefined,
): boolean {
  return (error?.statusCode ?? error?.status) === 404
    && status === 'error'
    && message.role === 'assistant'
    && lastMessageId === message.id
}
