import { and, asc, eq, inArray, sql, tables, useDrizzle } from './drizzle'

type Database = NonNullable<ReturnType<typeof useDrizzle>>
type MessageRole = 'user' | 'assistant' | 'system'
const MAX_DATABASE_LOCK_RETRIES = 6
const pendingChatWrites = new Map<string, Promise<void>>()

export interface AppendMessageInput {
  chatId: string
  id?: string
  parts: typeof tables.messages.$inferInsert.parts
  replaceExisting?: boolean
  requestId?: string
  role: MessageRole
}

export class MessageLifecycleError extends Error {
  constructor(
    readonly statusCode: number,
    message: string
  ) {
    super(message)
    this.name = 'MessageLifecycleError'
  }
}

async function findExistingMessage(db: Database, input: AppendMessageInput) {
  if (input.id) {
    const existingById = await db.select()
      .from(tables.messages)
      .where(eq(tables.messages.id, input.id))
      .limit(1)

    const message = existingById[0]
    if (message) {
      if (message.chatId !== input.chatId || message.role !== input.role) {
        throw new MessageLifecycleError(409, 'Message ID already belongs to a different chat or role')
      }

      return message
    }
  }

  if (!input.requestId) return undefined

  const existingByRequest = await db.select()
    .from(tables.messages)
    .where(and(
      eq(tables.messages.chatId, input.chatId),
      eq(tables.messages.requestId, input.requestId),
      eq(tables.messages.role, input.role)
    ))
    .limit(1)

  return existingByRequest[0]
}

async function replaceExistingMessage(
  db: Database,
  input: AppendMessageInput,
  existing: typeof tables.messages.$inferSelect
) {
  const updated = await db.update(tables.messages)
    .set({ parts: input.parts })
    .where(and(
      eq(tables.messages.id, existing.id),
      eq(tables.messages.chatId, input.chatId)
    ))
    .returning()

  return updated[0] ?? existing
}

function isDatabaseBusy(error: unknown): boolean {
  if (!(error instanceof Error)) return false

  const code = (error as Error & { code?: string }).code
  return code === 'SQLITE_BUSY' || error.message.includes('database is locked')
}

function waitForDatabaseLockRetry(attempt: number): Promise<void> {
  const delayMs = 10 * (attempt + 1)
  return new Promise(resolve => setTimeout(resolve, delayMs))
}

async function withDatabaseLockRetry<T>(operation: () => Promise<T>): Promise<T> {
  let lastError: unknown

  for (let attempt = 0; attempt <= MAX_DATABASE_LOCK_RETRIES; attempt++) {
    try {
      return await operation()
    } catch (error) {
      lastError = error
      if (isDatabaseBusy(error) && attempt < MAX_DATABASE_LOCK_RETRIES) {
        await waitForDatabaseLockRetry(attempt)
        continue
      }
      throw error
    }
  }

  throw lastError
}

async function withChatWriteLock<T>(chatId: string, operation: () => Promise<T>): Promise<T> {
  const previous = pendingChatWrites.get(chatId) ?? Promise.resolve()
  let release: (() => void) | undefined
  const current = new Promise<void>((resolve) => {
    release = resolve
  })
  pendingChatWrites.set(chatId, current)

  await previous
  try {
    return await operation()
  } finally {
    release?.()
    if (pendingChatWrites.get(chatId) === current) {
      pendingChatWrites.delete(chatId)
    }
  }
}

/**
 * Allocates the next message sequence and persists the message in the same
 * transaction. Retried request IDs return the existing message without
 * consuming another sequence.
 */
export async function appendMessage(db: Database, input: AppendMessageInput) {
  return withChatWriteLock(input.chatId, () => appendMessageWithRetries(db, input))
}

async function appendMessageWithRetries(db: Database, input: AppendMessageInput) {
  try {
    return await withDatabaseLockRetry(() => db.transaction(async (tx) => {
        const existing = await findExistingMessage(tx, input)
        if (existing) {
          return input.replaceExisting
            ? replaceExistingMessage(tx, input, existing)
            : existing
        }

        const allocation = await tx.update(tables.chats)
          .set({
            nextMessageSequence: sql`${tables.chats.nextMessageSequence} + 1`
          })
          .where(eq(tables.chats.id, input.chatId))
          .returning({
            historyRevision: tables.chats.historyRevision,
            sequence: sql<number>`${tables.chats.nextMessageSequence} - 1`
          })

        const current = allocation[0]
        if (!current) {
          throw new MessageLifecycleError(404, 'Chat not found')
        }

        const inserted = await tx.insert(tables.messages).values({
          chatId: input.chatId,
          historyRevision: current.historyRevision,
          id: input.id,
          parts: input.parts,
          requestId: input.requestId,
          role: input.role,
          sequence: current.sequence
        }).returning()

        const message = inserted[0]
        if (!message) {
          throw new MessageLifecycleError(500, 'Message insert did not return a row')
        }

        return message
      }))
  } catch (error) {
    if (!input.id && !input.requestId) throw error

    const existing = await findExistingMessage(db, input)
    if (existing) {
      return input.replaceExisting
        ? replaceExistingMessage(db, input, existing)
        : existing
    }

    throw error
  }
}

export interface TruncateHistoryInput {
  chatId: string
  messageId: string
  type: 'edit' | 'regenerate'
}

/**
 * Removes the mutable tail and advances the chat revision atomically. The
 * surviving messages retain their immutable sequence values.
 */
export async function truncateHistory(db: Database, input: TruncateHistoryInput) {
  return withChatWriteLock(input.chatId, () => withDatabaseLockRetry(() => db.transaction(async (tx) => {
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
        throw new MessageLifecycleError(404, 'Message not found')
      }

      const target = messages[targetIndex]!
      if (input.type === 'edit' && target.role !== 'user') {
        throw new MessageLifecycleError(400, 'Can only edit user messages')
      }
      if (input.type === 'regenerate' && target.role !== 'assistant') {
        throw new MessageLifecycleError(400, 'Can only regenerate assistant messages')
      }

      const startIndex = input.type === 'edit' ? targetIndex + 1 : targetIndex
      const idsToDelete = messages.slice(startIndex).map(message => message.id)
      if (idsToDelete.length > 0) {
        await tx.delete(tables.messages).where(inArray(tables.messages.id, idsToDelete))
      }

      const updated = await tx.update(tables.chats)
        .set({ historyRevision: sql`${tables.chats.historyRevision} + 1` })
        .where(eq(tables.chats.id, input.chatId))
        .returning({ historyRevision: tables.chats.historyRevision })

      const chat = updated[0]
      if (!chat) {
        throw new MessageLifecycleError(404, 'Chat not found')
      }

      return {
        deletedMessageIds: idsToDelete,
        historyRevision: chat.historyRevision
      }
    })))
}
