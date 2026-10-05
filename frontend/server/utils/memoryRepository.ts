import { createHash } from 'node:crypto'
import { and, asc, desc, eq, gt, inArray, isNull, or, sql } from 'drizzle-orm'
import type {
  MemoryFactCategory,
  MemoryFactStatus,
  MemorySnapshotStatus
} from '../database/schema'
import { tables, useDrizzle } from './drizzle'
import type { FactView } from './memoryContract'

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

export interface FactSourceMessageDto {
  historyRevision: number
  id: string
  parts: MessageRecord['parts']
  role: MessageRecord['role']
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

export interface ApplyCompactionPlanInput extends ReadMemoryInput {
  expectedActiveSnapshot: {
    id: string
    version: number
  } | null
  newSnapshot: Omit<WriteSnapshotInput, 'actorUserId' | 'chatId' | 'historyRevision' | 'version'>
  now?: Date
}

export type ApplyCompactionPlanResult =
  | { outcome: 'applied', snapshot: MemorySnapshotDto }
  | { outcome: 'conflict' }

export interface DeleteMemoryByChatInput {
  actorUserId: string
  chatId: string
}

export interface TruncateHistoryAndInvalidateMemoryInput {
  actorUserId: string
  chatId: string
  messageId: string
  now?: Date
  type: 'edit' | 'regenerate'
}

export interface TruncateHistoryAndInvalidateMemoryResult {
  deletedMessageIds: string[]
  historyRevision: number
  revokedFactCount: number
}

/** A client-facing mutation error with the route's established HTTP semantics. */
export class HistoryMutationError extends Error {
  constructor(
    readonly statusCode: 400 | 404 | 409,
    message: string
  ) {
    super(message)
    this.name = 'HistoryMutationError'
  }
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

/** Maps a repository record to the frozen browser-safe FactView contract. */
export function toFactView(fact: MemoryFactDto): FactView {
  return {
    id: fact.id,
    category: fact.category,
    status: fact.status,
    value: fact.value,
    sourceMessageId: fact.sourceMessageId,
    expiresAt: fact.expiresAt?.toISOString() ?? null,
    confirmedAt: fact.confirmedAt?.toISOString() ?? null,
    createdAt: fact.createdAt.toISOString()
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

const proposalWriteLocks = new Map<string, Promise<void>>()

async function serializeProposalWrite<T>(
  proposalKey: string,
  operation: () => Promise<T>
): Promise<T> {
  let release!: () => void
  const completion = new Promise<void>(resolve => { release = resolve })
  const predecessor = proposalWriteLocks.get(proposalKey) ?? Promise.resolve()
  proposalWriteLocks.set(proposalKey, completion)
  await predecessor

  try {
    return await operation()
  } finally {
    release()
    if (proposalWriteLocks.get(proposalKey) === completion) {
      proposalWriteLocks.delete(proposalKey)
    }
  }
}

const FACT_EXPIRY_MS: Record<MemoryFactCategory, number> = {
  GOAL: 90 * 24 * 60 * 60 * 1000,
  PREFERENCE: 90 * 24 * 60 * 60 * 1000,
  PLAN_CONSTRAINT: 30 * 24 * 60 * 60 * 1000
}

function calculateFactExpiry(category: MemoryFactCategory, confirmedAt: Date): Date {
  return new Date(confirmedAt.getTime() + FACT_EXPIRY_MS[category])
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

/** Read all current-revision messages for an internal compaction plan. */
export async function readRevisionMessages(
  db: Database,
  input: ReadMemoryInput
): Promise<TailMessageDto[]> {
  await requireOwnedChat(db, input.actorUserId, input.chatId)

  const messages = await db.select()
    .from(tables.messages)
    .where(and(
      eq(tables.messages.chatId, input.chatId),
      eq(tables.messages.historyRevision, input.historyRevision)
    ))
    .orderBy(asc(tables.messages.sequence))

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
    .orderBy(asc(tables.memoryFacts.createdAt), asc(tables.memoryFacts.id))

  return facts.map(toMemoryFactDto)
}

/**
 * Browser Fact management needs pending and confirmed records, while resolver
 * reads stay confirmed-only in getVisibleFacts().
 */
export async function getCurrentRevisionFacts(
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
      inArray(tables.memoryFacts.status, ['PROPOSED', 'CONFIRMED']),
      or(
        isNull(tables.memoryFacts.expiresAt),
        gt(tables.memoryFacts.expiresAt, now)
      )
    ))
    .orderBy(asc(tables.memoryFacts.createdAt), asc(tables.memoryFacts.id))

  return facts.map(toMemoryFactDto)
}

/**
 * Reads one actor-owned source without returning it to a browser. Callers must
 * still enforce the user-role and non-sensitive-text policies for their path.
 */
export async function readCurrentRevisionFactSource(
  db: Database,
  input: ReadMemoryInput & { sourceMessageId: string }
): Promise<FactSourceMessageDto | undefined> {
  await requireOwnedChat(db, input.actorUserId, input.chatId)
  const messages = await db.select({
    historyRevision: tables.messages.historyRevision,
    id: tables.messages.id,
    parts: tables.messages.parts,
    role: tables.messages.role
  })
    .from(tables.messages)
    .where(and(
      eq(tables.messages.id, input.sourceMessageId),
      eq(tables.messages.chatId, input.chatId),
      eq(tables.messages.historyRevision, input.historyRevision)
    ))
    .limit(1)

  return messages[0]
}

export async function createFactProposal(
  db: Database,
  input: CreateFactProposalInput
): Promise<CreateFactProposalResult> {
  const proposalKey = createProposalKey(input)
  const maxBusyRetries = 5

  return serializeProposalWrite(proposalKey, async () => {
    for (let attempt = 0; ; attempt += 1) {
      try {
        return await db.transaction(async (tx) => {
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
      } catch (error) {
        if (!isDatabaseBusyError(error) || attempt >= maxBusyRetries) throw error
        await new Promise(resolve => setTimeout(resolve, 50 * (attempt + 1)))
      }
    }
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

    const confirmedAt = input.now ?? new Date()
    const updated = await tx.update(tables.memoryFacts)
      .set({
        confirmedAt,
        expiresAt: calculateFactExpiry(fact.category, confirmedAt),
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

class CompactionConflictError extends Error {
  constructor () {
    super('The active Snapshot changed before the compaction plan could be applied')
  }
}

function isDatabaseBusyError (error: unknown): boolean {
  return typeof error === 'object'
    && error !== null
    && 'code' in error
    && (error as { code?: unknown }).code === 'SQLITE_BUSY'
}

/**
 * Atomically archive the expected ACTIVE Snapshot and create its successor.
 * A stale plan never changes the database and can be retried from a fresh read.
 */
export async function applyCompactionPlan(
  db: Database,
  input: ApplyCompactionPlanInput
): Promise<ApplyCompactionPlanResult> {
  try {
    return await db.transaction(async (tx) => {
      await requireOwnedChat(tx, input.actorUserId, input.chatId)
      const archivedAt = input.now ?? new Date()
      const nextVersion = input.expectedActiveSnapshot
        ? input.expectedActiveSnapshot.version + 1
        : 1

      if (input.expectedActiveSnapshot) {
        const archived = await tx.update(tables.memorySnapshots)
          .set({ archivedAt, status: 'ARCHIVED' })
          .where(and(
            eq(tables.memorySnapshots.id, input.expectedActiveSnapshot.id),
            eq(tables.memorySnapshots.userId, input.actorUserId),
            eq(tables.memorySnapshots.chatId, input.chatId),
            eq(tables.memorySnapshots.historyRevision, input.historyRevision),
            eq(tables.memorySnapshots.version, input.expectedActiveSnapshot.version),
            eq(tables.memorySnapshots.status, 'ACTIVE')
          ))
          .returning({ id: tables.memorySnapshots.id })
        if (!archived[0]) throw new CompactionConflictError()
      } else {
        const active = await tx.select({ id: tables.memorySnapshots.id })
          .from(tables.memorySnapshots)
          .where(and(
            eq(tables.memorySnapshots.userId, input.actorUserId),
            eq(tables.memorySnapshots.chatId, input.chatId),
            eq(tables.memorySnapshots.historyRevision, input.historyRevision),
            eq(tables.memorySnapshots.status, 'ACTIVE')
          ))
          .limit(1)
        if (active[0]) throw new CompactionConflictError()
      }

      const inserted = await tx.insert(tables.memorySnapshots)
        .values({
          chatId: input.chatId,
          coveredFromMessageId: input.newSnapshot.coveredFromMessageId,
          coveredFromSequence: input.newSnapshot.coveredFromSequence,
          coveredToMessageId: input.newSnapshot.coveredToMessageId,
          coveredToSequence: input.newSnapshot.coveredToSequence,
          historyRevision: input.historyRevision,
          status: 'ACTIVE',
          summary: input.newSnapshot.summary,
          userId: input.actorUserId,
          version: nextVersion
        })
        .onConflictDoNothing()
        .returning()
      if (!inserted[0]) throw new CompactionConflictError()

      return { outcome: 'applied', snapshot: toMemorySnapshotDto(inserted[0]) }
    })
  } catch (error) {
    if (error instanceof CompactionConflictError || isDatabaseBusyError(error)) {
      return { outcome: 'conflict' }
    }
    throw error
  }
}

/**
 * Deletes the mutable suffix and invalidates all Memory derived from the old
 * revision in one transaction. Snapshot rows deliberately remain as historical
 * records; every resolver is scoped to the chat's newly advanced revision.
 */
export async function truncateHistoryAndInvalidateMemory(
  db: Database,
  input: TruncateHistoryAndInvalidateMemoryInput
): Promise<TruncateHistoryAndInvalidateMemoryResult> {
  return db.transaction(async (tx) => {
    const chatRows = await tx.select({
      historyRevision: tables.chats.historyRevision,
      nextMessageSequence: tables.chats.nextMessageSequence
    })
      .from(tables.chats)
      .where(and(
        eq(tables.chats.id, input.chatId),
        eq(tables.chats.userId, input.actorUserId)
      ))
      .limit(1)
    const chat = chatRows[0]
    if (!chat) {
      throw new HistoryMutationError(404, 'Chat not found')
    }

    const messages = await tx.select({
      id: tables.messages.id,
      role: tables.messages.role,
      sequence: tables.messages.sequence
    })
      .from(tables.messages)
      .where(eq(tables.messages.chatId, input.chatId))
      .orderBy(asc(tables.messages.sequence))

    const targetIndex = messages.findIndex(message => message.id === input.messageId)
    if (targetIndex === -1) {
      throw new HistoryMutationError(404, 'Message not found')
    }

    const target = messages[targetIndex]!
    if (input.type === 'edit' && target.role !== 'user') {
      throw new HistoryMutationError(400, 'Can only edit user messages')
    }
    if (input.type === 'regenerate' && target.role !== 'assistant') {
      throw new HistoryMutationError(400, 'Can only regenerate assistant messages')
    }

    const startIndex = input.type === 'edit' ? targetIndex + 1 : targetIndex
    const deletedMessageIds = messages.slice(startIndex).map(message => message.id)
    if (deletedMessageIds.length > 0) {
      await tx.delete(tables.messages)
        .where(and(
          eq(tables.messages.chatId, input.chatId),
          inArray(tables.messages.id, deletedMessageIds)
        ))
    }

    const revoked = await tx.update(tables.memoryFacts)
      .set({
        revokedAt: input.now ?? new Date(),
        status: 'REVOKED'
      })
      .where(and(
        eq(tables.memoryFacts.userId, input.actorUserId),
        eq(tables.memoryFacts.chatId, input.chatId),
        eq(tables.memoryFacts.historyRevision, chat.historyRevision),
        eq(tables.memoryFacts.scope, 'SESSION'),
        inArray(tables.memoryFacts.status, ['PROPOSED', 'CONFIRMED'])
      ))
      .returning({ id: tables.memoryFacts.id })

    const updated = await tx.update(tables.chats)
      .set({ historyRevision: sql`${tables.chats.historyRevision} + 1` })
      .where(and(
        eq(tables.chats.id, input.chatId),
        eq(tables.chats.userId, input.actorUserId),
        eq(tables.chats.historyRevision, chat.historyRevision),
        // An append allocates a sequence in the same chat. If it raced this
        // mutation, roll back the deletion/Fact revocation rather than leave
        // a newly appended old-revision message outside the new lineage.
        eq(tables.chats.nextMessageSequence, chat.nextMessageSequence)
      ))
      .returning({ historyRevision: tables.chats.historyRevision })
    const nextChat = updated[0]
    if (!nextChat) {
      throw new HistoryMutationError(409, 'Chat history changed; retry the mutation')
    }

    return {
      deletedMessageIds,
      historyRevision: nextChat.historyRevision,
      revokedFactCount: revoked.length
    }
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
