export type ExplorationMode = 'auto' | 'off' | 'force'

export function chatExplorationMode(metadata: unknown, parts: unknown): ExplorationMode {
  const direct = (metadata as any)?.explorationMode
  if (direct === 'auto' || direct === 'off' || direct === 'force') return direct
  if (Array.isArray(parts)) {
    for (const part of parts) {
      if ((part as any)?.type !== 'data-chat-preferences') continue
      const value = (part as any)?.data?.exploration_mode
      if (value === 'auto' || value === 'off' || value === 'force') return value
    }
  }
  return 'auto'
}
