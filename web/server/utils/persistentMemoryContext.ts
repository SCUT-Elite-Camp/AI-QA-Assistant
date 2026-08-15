import { getActiveSnapshot, getVisibleFacts, readTailMessages, type MemoryFactDto, type MemorySnapshotDto, type TailMessageDto } from './memoryRepository'
import { memoryContextInputSchema, type MemoryContextInput } from './memoryContract'
import type { CurrentMessageHandoff } from './messageLifecycle'
import type { useDrizzle } from './drizzle'

type Database = NonNullable<ReturnType<typeof useDrizzle>>

function partsToText (parts: unknown): string {
  if (typeof parts === 'string') return parts
  if (!Array.isArray(parts)) return ''

  return parts
    .map((part) => {
      if (typeof part === 'string') return part
      if (part && typeof part === 'object' && typeof (part as { text?: unknown }).text === 'string') {
        return (part as { text: string }).text
      }
      return ''
    })
    .join('')
}

export function createPersistentMemoryContext (
  handoff: CurrentMessageHandoff,
  snapshot: MemorySnapshotDto | undefined,
  facts: MemoryFactDto[],
  tail: TailMessageDto[]
): MemoryContextInput {
  return memoryContextInputSchema.parse({
    actor: {
      user_id: handoff.actorUserId,
      authenticated: true
    },
    chat_id: handoff.chatId,
    revision: handoff.historyRevision,
    current_message_id: handoff.currentMessageId,
    current_sequence: handoff.currentSequence,
    snapshot: snapshot
      ? {
          id: snapshot.id,
          version: snapshot.version,
          revision: snapshot.historyRevision,
          covered_to_sequence: snapshot.coveredToSequence,
          summary: snapshot.summary
        }
      : null,
    facts: facts.map(fact => ({
      id: fact.id,
      category: fact.category,
      value: fact.value,
      expires_at: fact.expiresAt?.getTime() ?? null
    })),
    tail: tail
      .filter(message => message.id !== handoff.currentMessageId)
      .map(message => ({
        id: message.id,
        sequence: message.sequence,
        revision: message.historyRevision,
        role: message.role,
        content: partsToText(message.parts)
      }))
  })
}

/** The BFF is the only component that reads persistent Memory records. */
export async function buildPersistentMemoryContext (
  db: Database,
  handoff: CurrentMessageHandoff
): Promise<MemoryContextInput> {
  const memoryInput = {
    actorUserId: handoff.actorUserId,
    chatId: handoff.chatId,
    historyRevision: handoff.historyRevision
  }
  const snapshot = await getActiveSnapshot(db, memoryInput)
  const [facts, tail] = await Promise.all([
    getVisibleFacts(db, memoryInput),
    readTailMessages(db, {
      ...memoryInput,
      afterSequence: snapshot?.coveredToSequence ?? 0,
      // Unit 05, not the transport layer, applies the model-history window.
      limit: Number.MAX_SAFE_INTEGER
    })
  ])

  return createPersistentMemoryContext(handoff, snapshot, facts, tail)
}
