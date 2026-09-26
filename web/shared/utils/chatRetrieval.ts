export function knowledgeBaseRetrievalEnabled(metadata: unknown, parts: unknown = []): boolean {
  if (metadata && typeof metadata === 'object') {
    const value = (metadata as Record<string, unknown>).knowledgeBaseRetrievalEnabled
    if (typeof value === 'boolean') return value
  }

  for (const part of Array.isArray(parts) ? parts : []) {
    if (!part || typeof part !== 'object' || (part as any).type !== 'data-chat-preferences') continue
    const value = (part as any).data?.knowledge_base_retrieval_enabled
    if (typeof value === 'boolean') return value
  }
  return true
}
