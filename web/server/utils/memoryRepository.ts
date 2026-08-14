import { createHash } from 'node:crypto'
import { and, asc, desc, eq, gt, isNull, or } from 'drizzle-orm'
import type {
  MemoryFactCategory,
  MemoryFactStatus,
  MemorySnapshotStatus
} from '../database/schema'
import { tables, useDrizzle } from './drizzle'

type Database = NonNullable<ReturnType<typeof useDrizzle>>
type MemorySnapshotRecord = typeof tables.memorySnapshots.$inferSelect
type MemoryFactRecord = typeof tables.memoryFacts.$inferSelect
type MessageRecord = typeof tables.messages.$inferSelect

export interface MemorySnapshotDto {
  archivedAt: Date | null
  chatId: string
  coveredFromMessageId: string
  coveredFromSequence: number
  coveredToMessageId: string
  coveredToSequence: number
  createdAt: Date
  historyRevision: number
  id: string
  status: MemorySnapshotStatus
  summary: string
  version: number
}

export interface MemoryFactDto {
  category: MemoryFactCategory
  chatId: string
  confirmedAt: Date | null
  createdAt: Date
  expiresAt: Date | null
  historyRevision: number
  id: string
  proposalKey: string
  revokedAt: Date | null
  scope: 'SESSION'
  sourceMessageId: string | null
  status: MemoryFactStatus
  value: string
}

export interface TailMessageDto {
  createdAt: Date
  historyRevision: number
  id: string
  parts: MessageRecord['parts']
  role: MessageRecord['role']
  sequence: number
}

export class MemoryRepositoryError extends Error {
  constructor(
    readonly code: 'chat_not_found' | 'fact_not_found' | 'source_message_not_found',
    message: string
  ) {
    super(message)
    this.name = 'MemoryRepositoryError'
  }
}

export class MemoryFactRevokedError extends Error {
  readonly code = 'fact_revoked'

  constructor() {
    super('A revoked Fact cannot be confirmed again')
    this.name = 'MemoryFactRevokedError'
  }
}

export interface ReadMemoryInput {
  actorUserId: string
  chatId: string
  historyRevision: number
}

export interface ReadTailInput extends ReadMemoryInput {
  afterSequence: number
  limit: number
}

export interface CreateFactProposalInput extends ReadMemoryInput {
  category: MemoryFactCategory
  sourceMessageId: string
  value: string
}

export interface CreateFactProposalResult {
  created: boolean
  fact: MemoryFactDto
}

export interface ConfirmFactInput extends ReadMemoryInput {
  expiresAt: Date | null
  factId: string
  now?: Date
}

export interface RevokeFactInput extends ReadMemoryInput {
  factId: string
  now?: Date
}

export interface WriteSnapshotInput extends ReadMemoryInput {
  coveredFromMessageId: string
  coveredFromSequence: number
  coveredToMessageId: string
  coveredToSequence: number
  summary: string
  version: number
}

export interface ArchiveSnapshotInput extends ReadMemoryInput {
  now?: Date
  version: number
}

export interface DeleteMemoryByChatInput {
  actorUserId: string
  chatId: string
}

function toMemorySnapshotDto(snapshot: MemorySnapshotRecord): MemorySnapshotDto {
  return {
    archivedAt: snapshot.archivedAt,
    chatId: snapshot.chatId,
    coveredFromMessageId: snapshot.coveredFromMessageId,
    coveredFromSequence: snapshot.coveredFromSequence,
    coveredToMessageId: snapshot.coveredToMessageId,
    coveredToSequence: snapshot.coveredToSequence,
    createdAt: snapshot.createdAt,
    historyRevision: snapshot.historyRevision,
    id: snapshot.id,
    status: snapshot.status,
    summary: snapshot.summary,
    version: snapshot.version
  }
}

function toMemoryFactDto(fact: MemoryFactRecord): MemoryFactDto {
  return {
    category: fact.category,
    chatId: fact.chatId,
    confirmedAt: fact.confirmedAt,
    createdAt: fact.createdAt,
    expiresAt: fact.expiresAt,
    historyRevision: fact.historyRevision,
    id: fact.id,
    proposalKey: fact.proposalKey,
    revokedAt: fact.revokedAt,
    scope: fact.scope,
    sourceMessageId: fact.sourceMessageId,
    status: fact.status,
    value: fact.value
  }
}

function toTailMessageDto(message: MessageRecord): TailMessageDto {
  return {
    createdAt: message.createdAt,
    historyRevision: message.historyRevision,
    id: message.id,
    parts: message.parts,
    role: message.role,
    sequence: message.sequence
  }
}

function normalizeFactValue(value: string): string {
  return value.normalize('NFC').trim().replace(/\s+/gu, ' ')
}

function createProposalKey(input: CreateFactProposalInput): string {
  const normalizedValue = normalizeFactValue(input.value)
  const serialized = [
    input.chatId,
    input.historyRevision,
    input.sourceMessageId,
    input.category,
    normalizedValue
  ].join('\0')

  return createHash('sha256').update(serialized, 'utf8').digest('hex')
}

function validateTailWindow(input: ReadTailInput): void {
  if (!Number.isSafeInteger(input.afterSequence) || input.afterSequence < 0) {
    throw new RangeError('afterSequence must be a non-negative safe integer')
  }
  if (!Number.isSafeInteger(input.limit) || input.limit <= 0) {
    throw new RangeError('limit must be a positive safe integer')
  }
}

async function requireOwnedChat(db: Database, actorUserId: string, chatId: string) {
  const chat = await db.select({ id: tables.chats.id })
    .from(tables.chats)
    .where(and(
      eq(tables.chats.id, chatId),
      eq(tables.chats.userId, actorUserId)
    ))
    .limit(1)

  if (!chat[0]) {
    throw new MemoryRepositoryError('chat_not_found', 'Chat not found')
  }
}

async function requireSourceMessage(
  db: Database,
  input: CreateFactProposalInput
): Promise<void> {
  const message = await db.select({ id: tables.messages.id })
    .from(tables.messages)
    .where(and(
      eq(tables.messages.id, input.sourceMessageId),
      eq(tables.messages.chatId, input.chatId),
      eq(tables.messages.historyRevision, input.historyRevision)
    ))
    .limit(1)

  if (!message[0]) {
    throw new MemoryRepositoryError('source_message_not_found', 'Source message not found')
  }
}

async function getOwnedFact(
  db: Database,
  input: ReadMemoryInput & { factId: string }
): Promise<MemoryFactRecord> {
  const facts = await db.select()
    .from(tables.memoryFacts)
    .where(and(
      eq(tables.memoryFacts.id, input.factId),
      eq(tables.memoryFacts.userId, input.actorUserId),
      eq(tables.memoryFacts.chatId, input.chatId),
      eq(tables.memoryFacts.historyRevision, input.historyRevision)
    ))
    .limit(1)

  const fact = facts[0]
  if (!fact) {
    throw new MemoryRepositoryError('fact_not_found', 'Fact not found')
  }

  return fact
}

export async function getActiveSnapshot(
  db: Database,
  input: ReadMemoryInput
): Promise<MemorySnapshotDto | undefined> {
  await requireOwnedChat(db, input.actorUserId, input.chatId)

  const snapshots = await db.select()
    .from(tables.memorySnapshots)
    .where(and(
      eq(tables.memorySnapshots.userId, input.actorUserId),
      eq(tables.memorySnapshots.chatId, input.chatId),
      eq(tables.memorySnapshots.historyRevision, input.historyRevision),
      eq(tables.memorySnapshots.status, 'ACTIVE')
    ))
    .orderBy(desc(tables.memorySnapshots.version))
    .limit(1)

  return snapshots[0] ? toMemorySnapshotDto(snapshots[0]) : undefined
}

export async function readTailMessages(
  db: Database,
  input: ReadTailInput
): Promise<TailMessageDto[]> {
  validateTailWindow(input)
  await requireOwnedChat(db, input.actorUserId, input.chatId)

  const messages = await db.select()
    .from(tables.messages)
    .where(and(
      eq(tables.messages.chatId, input.chatId),
      eq(tables.messages.historyRevision, input.historyRevision),
      gt(tables.messages.sequence, input.afterSequence)
    ))
    .orderBy(asc(tables.messages.sequence))
    .limit(input.limit)

  return messages.map(toTailMessageDto)
}

export async function getVisibleFacts(
  db: Database,
  input: ReadMemoryInput & { now?: Date }
): Promise<MemoryFactDto[]> {
  await requireOwnedChat(db, input.actorUserId, input.chatId)
  const now = input.now ?? new Date()

  const facts = await db.select()
    .from(tables.memoryFacts)
    .where(and(
      eq(tables.memoryFacts.userId, input.actorUserId),
      eq(tables.memoryFacts.chatId, input.chatId),
      eq(tables.memoryFacts.historyRevision, input.historyRevision),
      eq(tables.memoryFacts.scope, 'SESSION'),
      eq(tables.memoryFacts.status, 'CONFIRMED'),
      or(
        isNull(tables.memoryFacts.expiresAt),
        gt(tables.memoryFacts.expiresAt, now)
      )
    ))
    .orderBy(asc(tables.memoryFacts.createdAt))

  return facts.map(toMemoryFactDto)
}

export async function createFactProposal(
  db: Database,
  input: CreateFactProposalInput
): Promise<CreateFactProposalResult> {
  const proposalKey = createProposalKey(input)

  return db.transaction(async (tx) => {
    await requireOwnedChat(tx, input.actorUserId, input.chatId)
    await requireSourceMessage(tx, input)

    const inserted = await tx.insert(tables.memoryFacts)
      .values({
        category: input.category,
        chatId: input.chatId,
        historyRevision: input.historyRevision,
        proposalKey,
        scope: 'SESSION',
        sourceMessageId: input.sourceMessageId,
        status: 'PROPOSED',
        userId: input.actorUserId,
        value: input.value
      })
      .onConflictDoNothing()
      .returning()

    if (inserted[0]) {
      return { created: true, fact: toMemoryFactDto(inserted[0]) }
    }

    const facts = await tx.select()
      .from(tables.memoryFacts)
      .where(and(
        eq(tables.memoryFacts.userId, input.actorUserId),
        eq(tables.memoryFacts.chatId, input.chatId),
        eq(tables.memoryFacts.historyRevision, input.historyRevision),
        eq(tables.memoryFacts.proposalKey, proposalKey)
      ))
      .limit(1)

    const existing = facts[0]
    if (!existing) {
      throw new Error('Fact proposal conflict did not return an existing Fact')
    }

    return { created: false, fact: toMemoryFactDto(existing) }
  })
}

export async function confirmFact(
  db: Database,
  input: ConfirmFactInput
): Promise<MemoryFactDto> {
  return db.transaction(async (tx) => {
    await requireOwnedChat(tx, input.actorUserId, input.chatId)
    const fact = await getOwnedFact(tx, input)

    if (fact.status === 'REVOKED') {
      throw new MemoryFactRevokedError()
    }
    if (fact.status === 'CONFIRMED') {
      return toMemoryFactDto(fact)
    }

    const updated = await tx.update(tables.memoryFacts)
      .set({
        confirmedAt: input.now ?? new Date(),
        expiresAt: input.expiresAt,
        status: 'CONFIRMED'
      })
      .where(and(
        eq(tables.memoryFacts.id, fact.id),
        eq(tables.memoryFacts.status, 'PROPOSED')
      ))
      .returning()

    const confirmed = updated[0]
    if (confirmed) {
      return toMemoryFactDto(confirmed)
    }

    const latest = await getOwnedFact(tx, input)
    if (latest.status === 'CONFIRMED') {
      return toMemoryFactDto(latest)
    }
    if (latest.status === 'REVOKED') {
      throw new MemoryFactRevokedError()
    }

    throw new MemoryRepositoryError('fact_not_found', 'Fact confirmation did not update the proposed Fact')
  })
}

export async function revokeFact(
  db: Database,
  input: RevokeFactInput
): Promise<MemoryFactDto> {
  return db.transaction(async (tx) => {
    await requireOwnedChat(tx, input.actorUserId, input.chatId)
    const fact = await getOwnedFact(tx, input)

    if (fact.status === 'REVOKED') {
      return toMemoryFactDto(fact)
    }

    const updated = await tx.update(tables.memoryFacts)
      .set({
        revokedAt: input.now ?? new Date(),
        status: 'REVOKED'
      })
      .where(and(
        eq(tables.memoryFacts.id, fact.id),
        eq(tables.memoryFacts.status, fact.status)
      ))
      .returning()

    const revoked = updated[0]
    if (revoked) {
      return toMemoryFactDto(revoked)
    }

    const latest = await getOwnedFact(tx, input)
    if (latest.status === 'REVOKED') {
      return toMemoryFactDto(latest)
    }

    throw new MemoryRepositoryError('fact_not_found', 'Fact revocation did not update the Fact')
  })
}

export async function archiveSnapshot(
  db: Database,
  input: ArchiveSnapshotInput
): Promise<MemorySnapshotDto | undefined> {
  return db.transaction(async (tx) => {
    await requireOwnedChat(tx, input.actorUserId, input.chatId)

    const archived = await tx.update(tables.memorySnapshots)
      .set({
        archivedAt: input.now ?? new Date(),
        status: 'ARCHIVED'
      })
      .where(and(
        eq(tables.memorySnapshots.userId, input.actorUserId),
        eq(tables.memorySnapshots.chatId, input.chatId),
        eq(tables.memorySnapshots.historyRevision, input.historyRevision),
        eq(tables.memorySnapshots.version, input.version),
        eq(tables.memorySnapshots.status, 'ACTIVE')
      ))
      .returning()

    return archived[0] ? toMemorySnapshotDto(archived[0]) : undefined
  })
}

export async function writeSnapshot(
  db: Database,
  input: WriteSnapshotInput
): Promise<MemorySnapshotDto> {
  return db.transaction(async (tx) => {
    await requireOwnedChat(tx, input.actorUserId, input.chatId)

    const inserted = await tx.insert(tables.memorySnapshots)
      .values({
        chatId: input.chatId,
        coveredFromMessageId: input.coveredFromMessageId,
        coveredFromSequence: input.coveredFromSequence,
        coveredToMessageId: input.coveredToMessageId,
        coveredToSequence: input.coveredToSequence,
        historyRevision: input.historyRevision,
        status: 'ACTIVE',
        summary: input.summary,
        userId: input.actorUserId,
        version: input.version
      })
      .returning()

    const snapshot = inserted[0]
    if (!snapshot) {
      throw new Error('Snapshot insert did not return a row')
    }

    return toMemorySnapshotDto(snapshot)
  })
}

export async function deleteMemoryByChat(
  db: Database,
  input: DeleteMemoryByChatInput
): Promise<{ deletedFactCount: number, deletedSnapshotCount: number }> {
  return db.transaction(async (tx) => {
    await requireOwnedChat(tx, input.actorUserId, input.chatId)

    const deletedFacts = await tx.delete(tables.memoryFacts)
      .where(and(
        eq(tables.memoryFacts.userId, input.actorUserId),
        eq(tables.memoryFacts.chatId, input.chatId)
      ))
      .returning({ id: tables.memoryFacts.id })
    const deletedSnapshots = await tx.delete(tables.memorySnapshots)
      .where(and(
        eq(tables.memorySnapshots.userId, input.actorUserId),
        eq(tables.memorySnapshots.chatId, input.chatId)
      ))
      .returning({ id: tables.memorySnapshots.id })

    return {
      deletedFactCount: deletedFacts.length,
      deletedSnapshotCount: deletedSnapshots.length
    }
  })
}
