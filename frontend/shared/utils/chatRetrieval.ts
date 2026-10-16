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

type RetrievalSource = 'enterprise_kb' | 'personal_library' | 'conversation_attachment'

/** Selection narrows sources; the BFF and Agent still establish every permission. */
export function retrievalSourceSelection(metadata: unknown, parts: unknown = []): RetrievalSource[] | undefined {
  let selected: unknown = metadata && typeof metadata === 'object'
    ? (metadata as Record<string, unknown>).retrievalSources : undefined
  if (selected === undefined) {
    const preference = (Array.isArray(parts) ? parts : []).find(part => part?.type === 'data-chat-preferences')
    selected = preference?.data?.retrieval_sources
  }
  if (selected === undefined) return undefined
  const allowed = new Set(['enterprise_kb', 'personal_library', 'conversation_attachment'])
  if (!Array.isArray(selected) || selected.length > 3 || selected.some(item => !allowed.has(item))) {
    throw new Error('invalid_retrieval_sources')
  }
  return [...new Set(selected)] as RetrievalSource[]
}
