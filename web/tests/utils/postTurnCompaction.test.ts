import { randomUUID } from 'node:crypto'
import { eq } from 'drizzle-orm'
import { describe, expect, it, vi } from 'vitest'

const environment = {
  AGENT_BASE_URL: 'http://agent.test',
  AGENT_INTERNAL_TOKEN: 'internal-token',
  PERSISTENT_MEMORY_ENABLED: 'true'
}

async function createPersistedTurnFixture (firstMessageText = 'turn-1') {
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
      parts: [{ text: sequence === 1 ? firstMessageText : `turn-${sequence}`, type: 'text' }],
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

function conflictingPlanResponse (request: {
  messages: Array<{ id: string, sequence: number }>
}) {
  return {
    ...successfulPlanResponse(request),
    expected_active_snapshot: {
      id: 'stale-snapshot-id',
      version: 1,
      revision: 1
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
    const request = JSON.parse(String(fetchFn.mock.calls[0]![1]?.body))
    expect(request).not.toHaveProperty('tail_size')
    expect(request).not.toHaveProperty('min_coverable_messages')
    expect(request).not.toHaveProperty('soft_token_budget')

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

  it('does not write a Snapshot when the Agent returns should_compact=false', async () => {
    const fixture = await createPersistedTurnFixture()
    const { compactAfterSuccessfulAssistantPersistence } = await import('../../server/utils/postTurnCompaction')
    const fetchFn = vi.fn().mockResolvedValue(new Response(JSON.stringify({ should_compact: false }), { status: 200 }))

    await expect(compactAfterSuccessfulAssistantPersistence(fixture.db, fixture.handoff, {
      environment,
      fetchFn
    })).resolves.toBe('not_needed')

    const snapshots = await fixture.db.select().from(fixture.tables.memorySnapshots)
      .where(eq(fixture.tables.memorySnapshots.chatId, fixture.handoff.chatId))
    expect(snapshots).toEqual([])
    expect(fetchFn).toHaveBeenCalledTimes(1)
  })

  it('does not log raw message text or an ACTIVE Snapshot summary while planning', async () => {
    const rawQuery = 'private query must not appear in logs'
    const snapshotSummary = 'private snapshot summary must not appear in logs'
    const fixture = await createPersistedTurnFixture(rawQuery)
    const { writeSnapshot } = await import('../../server/utils/memoryRepository')
    const { compactAfterSuccessfulAssistantPersistence } = await import('../../server/utils/postTurnCompaction')
    await writeSnapshot(fixture.db, {
      actorUserId: fixture.handoff.actorUserId,
      chatId: fixture.handoff.chatId,
      coveredFromMessageId: fixture.messages[0]!.id,
      coveredFromSequence: fixture.messages[0]!.sequence,
      coveredToMessageId: fixture.messages[1]!.id,
      coveredToSequence: fixture.messages[1]!.sequence,
      historyRevision: fixture.handoff.historyRevision,
      summary: snapshotSummary,
      version: 1
    })
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const consoleLog = vi.spyOn(console, 'log').mockImplementation(() => undefined)
    const consoleWarn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)

    try {
      await expect(compactAfterSuccessfulAssistantPersistence(fixture.db, fixture.handoff, {
        environment,
        fetchFn: vi.fn().mockResolvedValue(new Response(JSON.stringify({ should_compact: false }), { status: 200 }))
      })).resolves.toBe('not_needed')

      const logText = JSON.stringify([
        ...consoleError.mock.calls,
        ...consoleLog.mock.calls,
        ...consoleWarn.mock.calls
      ])
      expect(logText).not.toContain(rawQuery)
      expect(logText).not.toContain(snapshotSummary)
    } finally {
      consoleError.mockRestore()
      consoleLog.mockRestore()
      consoleWarn.mockRestore()
    }
  })

  it('stops after two optimistic conflicts without creating a Snapshot', async () => {
    const fixture = await createPersistedTurnFixture()
    const { compactAfterSuccessfulAssistantPersistence } = await import('../../server/utils/postTurnCompaction')
    const fetchFn = vi.fn(async (_url: string, init?: RequestInit) => {
      const request = JSON.parse(String(init?.body))
      return new Response(JSON.stringify(conflictingPlanResponse(request)), { status: 200 })
    })

    await expect(compactAfterSuccessfulAssistantPersistence(fixture.db, fixture.handoff, {
      environment,
      fetchFn
    })).resolves.toBe('conflict_exhausted')

    const snapshots = await fixture.db.select().from(fixture.tables.memorySnapshots)
      .where(eq(fixture.tables.memorySnapshots.chatId, fixture.handoff.chatId))
    expect(snapshots).toEqual([])
    expect(fetchFn).toHaveBeenCalledTimes(2)
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
