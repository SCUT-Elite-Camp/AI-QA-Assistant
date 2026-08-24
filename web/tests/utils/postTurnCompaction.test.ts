import { randomUUID } from 'node:crypto'
import { eq } from 'drizzle-orm'
import { describe, expect, it, vi } from 'vitest'

const environment = {
  AGENT_BASE_URL: 'http://agent.test',
  AGENT_INTERNAL_TOKEN: 'internal-token',
  PERSISTENT_MEMORY_ENABLED: 'true'
}

async function createPersistedTurnFixture () {
  const { tables, useDrizzle } = await import('../../server/utils/drizzle')
  const { appendMessage } = await import('../../server/utils/messageLifecycle')
  const db = useDrizzle()
  const suffix = randomUUID()
  const userId = `compaction-user-${suffix}`
  const chatId = `compaction-chat-${suffix}`
  await db.insert(tables.users).values({
    avatar: 'https://example.test/avatar.png',
    email: `${suffix}@example.test`,
    id: userId,
    name: 'Compaction User',
    provider: 'github',
    providerId: userId,
    username: `compaction-user-${suffix}`
  })
  await db.insert(tables.chats).values({ id: chatId, title: 'Compaction chat', userId })

  const messages = []
  for (let sequence = 1; sequence <= 20; sequence += 1) {
    messages.push(await appendMessage(db, {
      chatId,
      id: randomUUID(),
      parts: [{ text: `turn-${sequence}`, type: 'text' }],
      role: sequence % 2 === 0 ? 'assistant' : 'user'
    }))
  }

  const currentUserMessage = messages[18]!
  return {
    db,
    handoff: {
      actorUserId: userId,
      chatId,
      currentMessageId: currentUserMessage.id,
      currentSequence: currentUserMessage.sequence,
      historyRevision: currentUserMessage.historyRevision
    },
    messages,
    tables
  }
}

function successfulPlanResponse (request: {
  messages: Array<{ id: string, sequence: number }>
}) {
  return {
    should_compact: true,
    expected_active_snapshot: null,
    new_snapshot: {
      covered_from_sequence: request.messages[0]!.sequence,
      covered_to_sequence: request.messages[11]!.sequence,
      covered_from_message_id: request.messages[0]!.id,
      covered_to_message_id: request.messages[11]!.id,
      summary: 'Deterministic compacted history.'
    }
  }
}

describe('post-turn compaction', () => {
  it('does not read or call Agent compaction when persistent Memory is disabled', async () => {
    const fixture = await createPersistedTurnFixture()
    const { compactAfterSuccessfulAssistantPersistence } = await import('../../server/utils/postTurnCompaction')
    const fetchFn = vi.fn()

    await expect(compactAfterSuccessfulAssistantPersistence(fixture.db, fixture.handoff, {
      environment: { PERSISTENT_MEMORY_ENABLED: 'false' },
      fetchFn
    })).resolves.toBe('not_needed')
    expect(fetchFn).not.toHaveBeenCalled()
  })

  it('applies the Agent plan after the assistant turn is already persisted', async () => {
    const fixture = await createPersistedTurnFixture()
    const { compactAfterSuccessfulAssistantPersistence } = await import('../../server/utils/postTurnCompaction')
    const { buildPersistentMemoryContext } = await import('../../server/utils/persistentMemoryContext')
    const { appendMessage, createCurrentMessageHandoff } = await import('../../server/utils/messageLifecycle')
    const fetchFn = vi.fn(async (_url: string, init?: RequestInit) => {
      const request = JSON.parse(String(init?.body))
      return new Response(JSON.stringify(successfulPlanResponse(request)), { status: 200 })
    })

    await expect(compactAfterSuccessfulAssistantPersistence(fixture.db, fixture.handoff, {
      environment,
      fetchFn
    })).resolves.toBe('applied')
    expect(fetchFn).toHaveBeenCalledWith('http://agent.test/api/internal/memory/compaction-plan', expect.any(Object))

    const snapshots = await fixture.db.select().from(fixture.tables.memorySnapshots)
      .where(eq(fixture.tables.memorySnapshots.chatId, fixture.handoff.chatId))
    expect(snapshots).toEqual([expect.objectContaining({ status: 'ACTIVE', version: 1 })])

    const nextUserMessage = await appendMessage(fixture.db, {
      chatId: fixture.handoff.chatId,
      id: randomUUID(),
      parts: [{ text: 'next query', type: 'text' }],
      role: 'user'
    })
    const nextContext = await buildPersistentMemoryContext(
      fixture.db,
      createCurrentMessageHandoff(fixture.handoff.actorUserId, nextUserMessage)
    )
    expect(nextContext.snapshot?.covered_to_sequence).toBe(12)
    expect(nextContext.tail.map(message => message.sequence)).toEqual([13, 14, 15, 16, 17, 18, 19, 20])
    expect(nextContext.tail.some(message => message.id === nextUserMessage.id)).toBe(false)
  })

  it('keeps the successful assistant message and permits a later retry when planning fails', async () => {
    const fixture = await createPersistedTurnFixture()
    const { compactAfterSuccessfulAssistantPersistence } = await import('../../server/utils/postTurnCompaction')
    const failingFetch = vi.fn().mockResolvedValue(new Response('', { status: 500 }))

    await expect(compactAfterSuccessfulAssistantPersistence(fixture.db, fixture.handoff, {
      environment,
      fetchFn: failingFetch
    })).rejects.toMatchObject({ code: 'agent_internal_http_error' })
    const persistedAfterFailure = await fixture.db.select().from(fixture.tables.messages)
      .where(eq(fixture.tables.messages.chatId, fixture.handoff.chatId))
    expect(persistedAfterFailure).toHaveLength(20)

    const retryFetch = vi.fn(async (_url: string, init?: RequestInit) => {
      const request = JSON.parse(String(init?.body))
      return new Response(JSON.stringify(successfulPlanResponse(request)), { status: 200 })
    })
    await expect(compactAfterSuccessfulAssistantPersistence(fixture.db, fixture.handoff, {
      environment,
      fetchFn: retryFetch
    })).resolves.toBe('applied')
  })
})
