import { randomUUID } from 'node:crypto'
import { eq } from 'drizzle-orm'
import { describe, expect, it } from 'vitest'

async function createFixture() {
  const { tables, useDrizzle } = await import('../../server/utils/drizzle')
  const { appendMessage } = await import('../../server/utils/messageLifecycle')
  const db = useDrizzle()
  const suffix = randomUUID()
  const userId = `memory-user-${suffix}`
  const chatId = `memory-chat-${suffix}`

  await db.insert(tables.users).values({
    avatar: 'https://example.test/avatar.png',
    email: `${suffix}@memory.test`,
    id: userId,
    name: 'Memory Test User',
    provider: 'github',
    providerId: userId,
    username: `memory-user-${suffix}`
  })
  await db.insert(tables.chats).values({
    id: chatId,
    title: 'Memory test chat',
    userId
  })

  const source = await appendMessage(db, {
    chatId,
    id: randomUUID(),
    parts: [{ text: 'Please remember this preference.', type: 'text' }],
    requestId: `request-${suffix}`,
    role: 'user'
  })

  return { chatId, db, source, userId }
}

function snapshotInput(fixture: Awaited<ReturnType<typeof createFixture>>, version = 1) {
  return {
    actorUserId: fixture.userId,
    chatId: fixture.chatId,
    coveredFromMessageId: fixture.source.id,
    coveredFromSequence: fixture.source.sequence,
    coveredToMessageId: fixture.source.id,
    coveredToSequence: fixture.source.sequence,
    historyRevision: fixture.source.historyRevision,
    summary: 'The user asked us to remember a preference.',
    version
  }
}

describe('memory repository', () => {
  it('stores Memory for a provider-backed chat without a local users row', async () => {
    const { tables, useDrizzle } = await import('../../server/utils/drizzle')
    const { appendMessage } = await import('../../server/utils/messageLifecycle')
    const { writeSnapshot } = await import('../../server/utils/memoryRepository')
    const db = useDrizzle()
    const suffix = randomUUID()
    const userId = `github-provider-${suffix}`
    const chatId = `provider-chat-${suffix}`

    // OAuth sessions identify the chat owner by provider ID. A local profile
    // row is optional, so this must not require tables.users to contain userId.
    await db.insert(tables.chats).values({
      id: chatId,
      title: 'Provider-backed Memory chat',
      userId
    })
    const source = await appendMessage(db, {
      chatId,
      id: randomUUID(),
      parts: [{ text: 'Remember this session goal.', type: 'text' }],
      requestId: `provider-request-${suffix}`,
      role: 'user'
    })

    await expect(writeSnapshot(db, {
      actorUserId: userId,
      chatId,
      coveredFromMessageId: source.id,
      coveredFromSequence: source.sequence,
      coveredToMessageId: source.id,
      coveredToSequence: source.sequence,
      historyRevision: source.historyRevision,
      summary: 'Provider-backed session goal.',
      version: 1
    })).resolves.toMatchObject({ chatId })
  })

  it('cascades snapshots when their chat is deleted', async () => {
    const fixture = await createFixture()
    const { writeSnapshot } = await import('../../server/utils/memoryRepository')
    const { tables } = await import('../../server/utils/drizzle')

    await writeSnapshot(fixture.db, snapshotInput(fixture))
    await fixture.db.delete(tables.chats).where(eq(tables.chats.id, fixture.chatId))

    const snapshots = await fixture.db.select().from(tables.memorySnapshots)
      .where(eq(tables.memorySnapshots.chatId, fixture.chatId))

    expect(snapshots).toEqual([])
  })

  it('rejects a duplicate Snapshot version within one chat revision', async () => {
    const fixture = await createFixture()
    const { writeSnapshot } = await import('../../server/utils/memoryRepository')

    await writeSnapshot(fixture.db, snapshotInput(fixture))
    await expect(writeSnapshot(fixture.db, snapshotInput(fixture))).rejects.toThrow()
  })

  it('enforces one ACTIVE Snapshot per chat revision even when a caller bypasses the repository', async () => {
    const fixture = await createFixture()
    const { tables } = await import('../../server/utils/drizzle')
    const { writeSnapshot } = await import('../../server/utils/memoryRepository')
    const first = snapshotInput(fixture)

    await writeSnapshot(fixture.db, first)

    const bypassValues = {
      chatId: fixture.chatId,
      coveredFromMessageId: fixture.source.id,
      coveredFromSequence: fixture.source.sequence,
      coveredToMessageId: fixture.source.id,
      coveredToSequence: fixture.source.sequence,
      historyRevision: fixture.source.historyRevision,
      summary: 'Bypass write must still obey the ACTIVE Snapshot invariant.',
      userId: fixture.userId,
      version: 2
    }

    await expect(fixture.db.insert(tables.memorySnapshots).values({
      ...bypassValues,
      status: 'ACTIVE'
    })).rejects.toThrow()
    await expect(fixture.db.insert(tables.memorySnapshots).values({
      ...bypassValues,
      status: 'ARCHIVED'
    })).resolves.toBeDefined()
    await expect(fixture.db.insert(tables.memorySnapshots).values({
      ...bypassValues,
      historyRevision: fixture.source.historyRevision + 1,
      status: 'ACTIVE',
      version: 1
    })).resolves.toBeDefined()
  })

  it('advances revision and makes edited history Memory-invisible in the same transaction', async () => {
    const fixture = await createFixture()
    const { appendMessage, createCurrentMessageHandoff } = await import('../../server/utils/messageLifecycle')
    const { buildPersistentMemoryContext } = await import('../../server/utils/persistentMemoryContext')
    const { getActiveSnapshot, truncateHistoryAndInvalidateMemory, writeSnapshot } = await import('../../server/utils/memoryRepository')

    const priorAssistant = await appendMessage(fixture.db, {
      chatId: fixture.chatId,
      id: randomUUID(),
      parts: [{ text: 'Old assistant answer.', type: 'text' }],
      role: 'assistant'
    })
    const snapshot = await writeSnapshot(fixture.db, {
      ...snapshotInput(fixture),
      coveredToMessageId: priorAssistant.id,
      coveredToSequence: priorAssistant.sequence
    })

    const result = await truncateHistoryAndInvalidateMemory(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      messageId: fixture.source.id,
      now: new Date('2026-08-15T00:00:00.000Z'),
      type: 'edit'
    })
    expect(result).toEqual({
      deletedMessageIds: [priorAssistant.id],
      historyRevision: 2,})

    const edited = await appendMessage(fixture.db, {
      chatId: fixture.chatId,
      id: fixture.source.id,
      parts: [{ text: 'Edited question.', type: 'text' }],
      replaceExisting: true,
      requestId: fixture.source.requestId!,
      role: 'user'
    })
    const oldSnapshot = await getActiveSnapshot(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      historyRevision: 1
    })
    const newSnapshot = await getActiveSnapshot(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      historyRevision: 2
    })
    const context = await buildPersistentMemoryContext(
      fixture.db,
      createCurrentMessageHandoff(fixture.userId, edited)
    )

    expect(oldSnapshot).toEqual(snapshot)
    expect(newSnapshot).toBeUndefined()
    expect(context).toMatchObject({ snapshot: null, tail: [] })
  })

  it('removes the regenerated assistant answer and never resolves it from the new revision', async () => {
    const fixture = await createFixture()
    const { appendMessage, createCurrentMessageHandoff } = await import('../../server/utils/messageLifecycle')
    const { buildPersistentMemoryContext } = await import('../../server/utils/persistentMemoryContext')
    const { truncateHistoryAndInvalidateMemory, writeSnapshot } = await import('../../server/utils/memoryRepository')

    const oldAssistant = await appendMessage(fixture.db, {
      chatId: fixture.chatId,
      id: randomUUID(),
      parts: [{ text: 'Old regenerated answer.', type: 'text' }],
      role: 'assistant'
    })
    await writeSnapshot(fixture.db, {
      ...snapshotInput(fixture),
      coveredToMessageId: oldAssistant.id,
      coveredToSequence: oldAssistant.sequence
    })

    await truncateHistoryAndInvalidateMemory(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      messageId: oldAssistant.id,
      type: 'regenerate'
    })
    await appendMessage(fixture.db, {
      chatId: fixture.chatId,
      id: fixture.source.id,
      parts: fixture.source.parts,
      replaceExisting: true,
      requestId: fixture.source.requestId!,
      role: 'user'
    })
    const newAssistant = await appendMessage(fixture.db, {
      chatId: fixture.chatId,
      id: randomUUID(),
      parts: [{ text: 'New regenerated answer.', type: 'text' }, { type: 'data-evidence-provenance', data: { schema_version: 'evidence.provenance.v1', complete: true, dependencies: [] } }],
      role: 'assistant'
    })
    const nextUser = await appendMessage(fixture.db, {
      chatId: fixture.chatId,
      id: randomUUID(),
      parts: [{ text: 'Follow-up after regeneration.', type: 'text' }],
      requestId: randomUUID(),
      role: 'user'
    })
    const { tables } = await import('../../server/utils/drizzle')
    const remainingOldAnswer = await fixture.db.select().from(tables.messages)
      .where(eq(tables.messages.id, oldAssistant.id))
    const context = await buildPersistentMemoryContext(
      fixture.db,
      createCurrentMessageHandoff(fixture.userId, nextUser)
    )

    expect(remainingOldAnswer).toEqual([])
    expect(context.snapshot).toBeNull()
    expect(context.tail).toEqual(expect.arrayContaining([
      expect.objectContaining({ content: 'New regenerated answer.', id: newAssistant.id })
    ]))
    expect(context.tail).not.toEqual(expect.arrayContaining([
      expect.objectContaining({ content: 'Old regenerated answer.', id: oldAssistant.id })
    ]))
  })

  it('does not let a different user mutate a chat or its Memory', async () => {
    const fixture = await createFixture()
    const { getActiveSnapshot, truncateHistoryAndInvalidateMemory, writeSnapshot } = await import('../../server/utils/memoryRepository')

    const snapshot = await writeSnapshot(fixture.db, snapshotInput(fixture))
    await expect(truncateHistoryAndInvalidateMemory(fixture.db, {
      actorUserId: `attacker-${randomUUID()}`,
      chatId: fixture.chatId,
      messageId: fixture.source.id,
      type: 'edit'
    })).rejects.toMatchObject({ statusCode: 404 })

    const { tables } = await import('../../server/utils/drizzle')
    const [chat] = await fixture.db.select().from(tables.chats)
      .where(eq(tables.chats.id, fixture.chatId))
    expect(chat?.historyRevision).toBe(1)
    expect(await getActiveSnapshot(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      historyRevision: 1
    })).toEqual(snapshot)
  })

  it('keeps branch sequence and persistent Memory isolated from its parent chat', async () => {
    const fixture = await createFixture()
    const { appendMessage } = await import('../../server/utils/messageLifecycle')
    const { getActiveSnapshot, writeSnapshot } = await import('../../server/utils/memoryRepository')
    const { tables } = await import('../../server/utils/drizzle')
    const parentSnapshot = await writeSnapshot(fixture.db, snapshotInput(fixture))

    const branchId = randomUUID()
    await fixture.db.insert(tables.chats).values({
      id: branchId,
      isBranch: true,
      parentChatId: fixture.chatId,
      parentMessageId: fixture.source.id,
      title: 'Isolated branch',
      userId: fixture.userId
    })
    const branchMessage = await appendMessage(fixture.db, {
      chatId: branchId,
      id: randomUUID(),
      parts: [{ text: 'Branch question.', type: 'text' }],
      role: 'user'
    })

    expect(branchMessage).toMatchObject({ historyRevision: 1, sequence: 1 })
    expect(await getActiveSnapshot(fixture.db, {
      actorUserId: fixture.userId,
      chatId: branchId,
      historyRevision: 1
    })).toBeUndefined()
    expect(await getActiveSnapshot(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      historyRevision: 1
    })).toEqual(parentSnapshot)
  })

  it('atomically archives the expected ACTIVE Snapshot before creating its next version', async () => {
    const fixture = await createFixture()
    const { appendMessage } = await import('../../server/utils/messageLifecycle')
    const { applyCompactionPlan, getActiveSnapshot } = await import('../../server/utils/memoryRepository')
    const { tables } = await import('../../server/utils/drizzle')

    const messages = [fixture.source]
    for (let sequence = 2; sequence <= 32; sequence += 1) {
      messages.push(await appendMessage(fixture.db, {
        chatId: fixture.chatId,
        id: randomUUID(),
        parts: [{ text: `message-${sequence}`, type: 'text' }],
        role: sequence % 2 === 0 ? 'assistant' : 'user'
      }))
    }

    const first = await applyCompactionPlan(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      historyRevision: fixture.source.historyRevision,
      expectedActiveSnapshot: null,
      newSnapshot: {
        coveredFromMessageId: messages[0]!.id,
        coveredFromSequence: 1,
        coveredToMessageId: messages[11]!.id,
        coveredToSequence: 12,
        summary: 'First twelve messages.'
      }
    })
    expect(first).toMatchObject({ outcome: 'applied', snapshot: { status: 'ACTIVE', version: 1 } })
    if (first.outcome !== 'applied') throw new Error('first compaction should apply')

    const second = await applyCompactionPlan(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      historyRevision: fixture.source.historyRevision,
      expectedActiveSnapshot: { id: first.snapshot.id, version: first.snapshot.version },
      newSnapshot: {
        coveredFromMessageId: messages[12]!.id,
        coveredFromSequence: 13,
        coveredToMessageId: messages[23]!.id,
        coveredToSequence: 24,
        summary: 'First twenty-four messages.'
      }
    })
    expect(second).toMatchObject({ outcome: 'applied', snapshot: { status: 'ACTIVE', version: 2 } })

    const snapshots = await fixture.db.select().from(tables.memorySnapshots)
      .where(eq(tables.memorySnapshots.chatId, fixture.chatId))
      .orderBy(tables.memorySnapshots.version)
    expect(snapshots.map(snapshot => snapshot.status)).toEqual(['ARCHIVED', 'ACTIVE'])
    expect(snapshots.filter(snapshot => snapshot.status === 'ACTIVE')).toHaveLength(1)
    expect((await getActiveSnapshot(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      historyRevision: fixture.source.historyRevision
    }))?.version).toBe(2)
  })

  it('does not create two ACTIVE Snapshots when concurrent plans start without one', async () => {
    const fixture = await createFixture()
    const { appendMessage } = await import('../../server/utils/messageLifecycle')
    const { applyCompactionPlan } = await import('../../server/utils/memoryRepository')
    const { tables } = await import('../../server/utils/drizzle')

    const messages = [fixture.source]
    for (let sequence = 2; sequence <= 20; sequence += 1) {
      messages.push(await appendMessage(fixture.db, {
        chatId: fixture.chatId,
        id: randomUUID(),
        parts: [{ text: `message-${sequence}`, type: 'text' }],
        role: sequence % 2 === 0 ? 'assistant' : 'user'
      }))
    }
    const input = {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      historyRevision: fixture.source.historyRevision,
      expectedActiveSnapshot: null,
      newSnapshot: {
        coveredFromMessageId: messages[0]!.id,
        coveredFromSequence: 1,
        coveredToMessageId: messages[11]!.id,
        coveredToSequence: 12,
        summary: 'Concurrent compaction.'
      }
    }

    const outcomes = await Promise.all([
      applyCompactionPlan(fixture.db, input),
      applyCompactionPlan(fixture.db, input)
    ])
    expect(outcomes.map(result => result.outcome).sort()).toEqual(['applied', 'conflict'])

    const active = await fixture.db.select().from(tables.memorySnapshots)
      .where(eq(tables.memorySnapshots.status, 'ACTIVE'))
    expect(active.filter(snapshot => snapshot.chatId === fixture.chatId)).toHaveLength(1)
  })
})
