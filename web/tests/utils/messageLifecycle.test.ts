import { describe, expect, it } from 'vitest'

async function createFixture() {
  const { tables, useDrizzle } = await import('../../server/utils/drizzle')
  const db = useDrizzle()
  const userId = crypto.randomUUID()
  const chatId = crypto.randomUUID()

  await db.insert(tables.users).values({
    avatar: 'https://example.test/avatar.png',
    email: `${userId}@example.test`,
    id: userId,
    name: 'Lifecycle Test User',
    provider: 'github',
    providerId: userId,
    username: `user-${userId}`
  })
  await db.insert(tables.chats).values({
    id: chatId,
    title: 'Lifecycle Test Chat',
    userId
  })

  return { chatId, db }
}

describe('message lifecycle', () => {
  it('allocates a monotonic sequence and inherits the active history revision', async () => {
    const { appendMessage } = await import('../../server/utils/messageLifecycle')
    const { chatId, db } = await createFixture()

    const userMessage = await appendMessage(db, {
      chatId,
      id: crypto.randomUUID(),
      parts: [{ text: 'hello', type: 'text' }],
      requestId: crypto.randomUUID(),
      role: 'user'
    })
    const assistantMessage = await appendMessage(db, {
      chatId,
      id: crypto.randomUUID(),
      parts: [{ text: 'hi', type: 'text' }],
      role: 'assistant'
    })

    expect(userMessage).toMatchObject({ historyRevision: 1, sequence: 1 })
    expect(assistantMessage).toMatchObject({ historyRevision: 1, sequence: 2 })
  })

  it('builds the trusted Agent handoff from the persisted user message', async () => {
    const { appendMessage, createCurrentMessageHandoff } = await import('../../server/utils/messageLifecycle')
    const { chatId, db } = await createFixture()
    const actorUserId = crypto.randomUUID()
    const message = await appendMessage(db, {
      chatId,
      id: crypto.randomUUID(),
      parts: [{ text: 'handoff', type: 'text' }],
      requestId: crypto.randomUUID(),
      role: 'user'
    })

    expect(createCurrentMessageHandoff(actorUserId, message)).toEqual({
      actorUserId,
      chatId,
      currentMessageId: message.id,
      currentSequence: 1,
      historyRevision: 1
    })
  })

  it('returns the existing user message for concurrent request retries', async () => {
    const { appendMessage } = await import('../../server/utils/messageLifecycle')
    const { chatId, db } = await createFixture()
    const messageId = crypto.randomUUID()
    const requestId = crypto.randomUUID()
    const input = {
      chatId,
      id: messageId,
      parts: [{ text: 'retry me', type: 'text' }],
      requestId,
      role: 'user' as const
    }

    const [first, retry] = await Promise.all([
      appendMessage(db, input),
      appendMessage(db, input)
    ])

    expect(first.id).toBe(messageId)
    expect(retry).toMatchObject({ id: messageId, sequence: 1 })
  })

  it('updates an edited message without consuming another sequence', async () => {
    const { appendMessage, truncateHistory } = await import('../../server/utils/messageLifecycle')
    const { chatId, db } = await createFixture()
    const id = crypto.randomUUID()

    const original = await appendMessage(db, {
      chatId,
      id,
      parts: [{ text: 'original text', type: 'text' }],
      requestId: id,
      role: 'user'
    })
    await appendMessage(db, {
      chatId,
      id: crypto.randomUUID(),
      parts: [{ text: 'old assistant answer', type: 'text' }],
      role: 'assistant'
    })
    await truncateHistory(db, {
      chatId,
      messageId: id,
      type: 'edit'
    })
    const edited = await appendMessage(db, {
      chatId,
      id,
      parts: [{ text: 'edited text', type: 'text' }],
      replaceExisting: true,
      requestId: id,
      role: 'user'
    })
    const following = await appendMessage(db, {
      chatId,
      id: crypto.randomUUID(),
      parts: [{ text: 'next text', type: 'text' }],
      role: 'assistant'
    })

    expect(edited).toMatchObject({ historyRevision: 2, id: original.id, sequence: 1 })
    expect(edited.parts).toEqual([{ text: 'edited text', type: 'text' }])
    expect(following.sequence).toBe(3)
  })

  it('returns the existing message unchanged for a same-revision retry', async () => {
    const { appendMessage } = await import('../../server/utils/messageLifecycle')
    const { chatId, db } = await createFixture()
    const id = crypto.randomUUID()

    await appendMessage(db, {
      chatId,
      id,
      parts: [{ text: 'original text', type: 'text' }],
      requestId: id,
      role: 'user'
    })
    const retried = await appendMessage(db, {
      chatId,
      id,
      parts: [{ text: 'must not overwrite', type: 'text' }],
      replaceExisting: true,
      requestId: id,
      role: 'user'
    })

    expect(retried).toMatchObject({ historyRevision: 1, id, sequence: 1 })
    expect(retried.parts).toEqual([{ text: 'original text', type: 'text' }])
  })

  it('allows persistence only for a completed, non-aborted assistant response', async () => {
    const { shouldPersistAssistantMessage } = await import('../../server/utils/messageLifecycle')

    expect(shouldPersistAssistantMessage({
      assistantResponseCompleted: true,
      isAborted: false,
      responseRole: 'assistant'
    })).toBe(true)
    expect(shouldPersistAssistantMessage({
      assistantResponseCompleted: false,
      isAborted: false,
      responseRole: 'assistant'
    })).toBe(false)
    expect(shouldPersistAssistantMessage({
      assistantResponseCompleted: true,
      isAborted: true,
      responseRole: 'assistant'
    })).toBe(false)
    expect(shouldPersistAssistantMessage({
      assistantResponseCompleted: true,
      isAborted: false,
      responseRole: 'user'
    })).toBe(false)
  })

  it('serializes concurrent allocations without duplicate sequences', async () => {
    const { appendMessage } = await import('../../server/utils/messageLifecycle')
    const { chatId, db } = await createFixture()

    const messages = await Promise.all(
      Array.from({ length: 6 }, (_, index) => appendMessage(db, {
        chatId,
        id: crypto.randomUUID(),
        parts: [{ text: `message-${index}`, type: 'text' }],
        requestId: crypto.randomUUID(),
        role: 'user'
      }))
    )

    expect(messages.map(message => message.sequence).sort((a, b) => a - b)).toEqual([1, 2, 3, 4, 5, 6])
  })

  it('truncates by sequence and advances the history revision', async () => {
    const { appendMessage, truncateHistory } = await import('../../server/utils/messageLifecycle')
    const { chatId, db } = await createFixture()

    await appendMessage(db, {
      chatId,
      id: crypto.randomUUID(),
      parts: [{ text: 'first user message', type: 'text' }],
      requestId: crypto.randomUUID(),
      role: 'user'
    })
    const firstAssistant = await appendMessage(db, {
      chatId,
      id: crypto.randomUUID(),
      parts: [{ text: 'first assistant message', type: 'text' }],
      role: 'assistant'
    })
    await appendMessage(db, {
      chatId,
      id: crypto.randomUUID(),
      parts: [{ text: 'second user message', type: 'text' }],
      requestId: crypto.randomUUID(),
      role: 'user'
    })

    const result = await truncateHistory(db, {
      chatId,
      messageId: firstAssistant.id,
      type: 'regenerate'
    })
    const regeneratedAssistant = await appendMessage(db, {
      chatId,
      id: crypto.randomUUID(),
      parts: [{ text: 'regenerated answer', type: 'text' }],
      role: 'assistant'
    })

    expect(result).toMatchObject({ historyRevision: 2 })
    expect(result.deletedMessageIds).toContain(firstAssistant.id)
    expect(regeneratedAssistant).toMatchObject({ historyRevision: 2, sequence: 4 })
  })
})
