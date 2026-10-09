import { getActiveSnapshot, getVisibleFacts, readTailMessages, type MemoryFactDto, type MemorySnapshotDto, type TailMessageDto } from './memoryRepository'
import { memoryContextInputSchema, type MemoryContextInput } from './memoryContract'
import { isSessionFactEnabled } from './sessionFactGate'
import type { CurrentMessageHandoff } from './messageLifecycle'
import type { useDrizzle } from './drizzle'
import { assertMessageSources, assertSourceDependencies, messageProvenance } from './sourceAccess'

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
          summary: snapshot.summary,
          source_dependencies: snapshot.evidenceProvenance?.dependencies ?? [],
          provenance_complete: snapshot.evidenceProvenance?.complete ?? false,
        }
      : null,
    facts: facts.map(fact => ({
      id: fact.id,
      category: fact.category,
      value: fact.value,
      expires_at: fact.expiresAt?.getTime() ?? null,
      source_dependencies: fact.evidenceProvenance?.dependencies ?? [],
      provenance_complete: fact.evidenceProvenance?.complete ?? false,
    })),
    tail: tail
      .filter(message => message.id !== handoff.currentMessageId)
      .map(message => ({
        id: message.id,
        sequence: message.sequence,
        revision: message.historyRevision,
        role: message.role,
        content: partsToText(message.parts),
        source_dependencies: messageProvenance(message.parts)?.dependencies ?? [],
        provenance_complete: messageProvenance(message.parts)?.complete ?? false,
      }))
  })
}

/** The BFF is the only component that reads persistent Memory records. */
export async function buildPersistentMemoryContext (
  db: Database,
  handoff: CurrentMessageHandoff,
  options: { includeFacts?: boolean } = {}
): Promise<MemoryContextInput> {
  const memoryInput = {
    actorUserId: handoff.actorUserId,
    chatId: handoff.chatId,
    historyRevision: handoff.historyRevision
  }
  // Legacy snapshots and Facts have no dependency provenance. Do not promote
  // them to trusted context just because an owner previously confirmed them.
  const [candidateSnapshot, candidateFacts, tail] = await Promise.all([
    getActiveSnapshot(db, memoryInput),
    options.includeFacts !== false && isSessionFactEnabled() ? getVisibleFacts(db, memoryInput) : Promise.resolve([] as MemoryFactDto[]),
    readTailMessages(db, {
      ...memoryInput,
      afterSequence: 0,
      // Unit 05, not the transport layer, applies the model-history window.
      limit: 24,
    })
  ])

  let snapshot: MemorySnapshotDto | undefined
  if (candidateSnapshot?.evidenceProvenance?.complete) {
    try { await assertSourceDependencies(handoff.actorUserId, candidateSnapshot.evidenceProvenance.dependencies); snapshot = candidateSnapshot } catch { /* quarantine */ }
  }
  const facts: MemoryFactDto[] = []
  for (const fact of candidateFacts) {
    if (!fact.evidenceProvenance?.complete) continue
    try { await assertSourceDependencies(handoff.actorUserId, fact.evidenceProvenance.dependencies); facts.push(fact) } catch { /* quarantine */ }
  }

  const trustedTail = []
  for (const message of tail) {
    if (message.id === handoff.currentMessageId || message.sequence >= handoff.currentSequence || message.sequence <= (snapshot?.coveredToSequence ?? 0)) continue
    try { await assertMessageSources(handoff.actorUserId, message); trustedTail.push(message) } catch { /* never replay denied or unknown content */ }
  }
  return createPersistentMemoryContext(handoff, snapshot, facts, trustedTail)
}
