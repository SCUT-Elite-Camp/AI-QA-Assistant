import {
  requestCompactionPlan,
  type AgentInternalClientOptions
} from './agentInternalClient'
import {
  applyCompactionPlan,
  getActiveSnapshot,
  readRevisionMessages,
  type MemorySnapshotDto,
  type TailMessageDto
} from './memoryRepository'
import {
  compactionPlanRequestSchema,
  type CompactionPlanRequest
} from './memoryContract'
import type { useDrizzle } from './drizzle'
import type { CurrentMessageHandoff } from './messageLifecycle'

type Database = NonNullable<ReturnType<typeof useDrizzle>>

export const COMPACTION_TAIL_SIZE = 8
export const COMPACTION_MIN_COVERABLE_MESSAGES = 12
export const COMPACTION_SOFT_TOKEN_BUDGET = 1000
const MAX_COMPACTION_ATTEMPTS = 2

function partsToText (parts: unknown): string {
  if (typeof parts === 'string') return parts
  if (!Array.isArray(parts)) return ''

  return parts.map((part) => {
    if (typeof part === 'string') return part
    if (part && typeof part === 'object' && typeof (part as { text?: unknown }).text === 'string') {
      return (part as { text: string }).text
    }
    return ''
  }).join('')
}

function toActiveSnapshotInput (snapshot: MemorySnapshotDto | undefined) {
  return snapshot
    ? {
        id: snapshot.id,
        version: snapshot.version,
        revision: snapshot.historyRevision,
        covered_to_sequence: snapshot.coveredToSequence,
        summary: snapshot.summary
      }
    : null
}

function toCompactionMessages (messages: TailMessageDto[]) {
  return messages.map(message => ({
    id: message.id,
    sequence: message.sequence,
    revision: message.historyRevision,
    role: message.role,
    content: partsToText(message.parts)
  }))
}

export async function buildCompactionPlanRequest (
  db: Database,
  handoff: CurrentMessageHandoff
): Promise<CompactionPlanRequest> {
  const readInput = {
    actorUserId: handoff.actorUserId,
    chatId: handoff.chatId,
    historyRevision: handoff.historyRevision
  }
  const [activeSnapshot, messages] = await Promise.all([
    getActiveSnapshot(db, readInput),
    readRevisionMessages(db, readInput)
  ])

  return compactionPlanRequestSchema.parse({
    actor: { user_id: handoff.actorUserId, authenticated: true },
    chat_id: handoff.chatId,
    revision: handoff.historyRevision,
    active_snapshot: toActiveSnapshotInput(activeSnapshot),
    messages: toCompactionMessages(messages),
    tail_size: COMPACTION_TAIL_SIZE,
    min_coverable_messages: COMPACTION_MIN_COVERABLE_MESSAGES,
    soft_token_budget: COMPACTION_SOFT_TOKEN_BUDGET
  })
}

export type PostTurnCompactionResult = 'applied' | 'conflict_exhausted' | 'not_needed'

/**
 * Request a pure Agent plan only after an assistant message is durable, then
 * apply it with an optimistic, bounded retry. It intentionally has no queue.
 */
export async function compactAfterSuccessfulAssistantPersistence (
  db: Database,
  handoff: CurrentMessageHandoff,
  options?: AgentInternalClientOptions
): Promise<PostTurnCompactionResult> {
  for (let attempt = 0; attempt < MAX_COMPACTION_ATTEMPTS; attempt += 1) {
    const request = await buildCompactionPlanRequest(db, handoff)
    const plan = await requestCompactionPlan(request, options)
    if (!plan.should_compact) return 'not_needed'

    const result = await applyCompactionPlan(db, {
      actorUserId: handoff.actorUserId,
      chatId: handoff.chatId,
      historyRevision: handoff.historyRevision,
      expectedActiveSnapshot: plan.expected_active_snapshot
        ? { id: plan.expected_active_snapshot.id, version: plan.expected_active_snapshot.version }
        : null,
      newSnapshot: {
        coveredFromMessageId: plan.new_snapshot.covered_from_message_id,
        coveredFromSequence: plan.new_snapshot.covered_from_sequence,
        coveredToMessageId: plan.new_snapshot.covered_to_message_id,
        coveredToSequence: plan.new_snapshot.covered_to_sequence,
        summary: plan.new_snapshot.summary
      }
    })
    if (result.outcome === 'applied') return 'applied'
  }

  return 'conflict_exhausted'
}
