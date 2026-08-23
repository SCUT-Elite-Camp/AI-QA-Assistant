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

function proposalInput(fixture: Awaited<ReturnType<typeof createFixture>>) {
  return {
    actorUserId: fixture.userId,
    category: 'PREFERENCE' as const,
    chatId: fixture.chatId,
    historyRevision: fixture.source.historyRevision,
    sourceMessageId: fixture.source.id,
    value: 'Use concise Chinese responses.'
  }
}

describe('memory repository', () => {
  it('cascades snapshots and Facts when their chat is deleted', async () => {
    const fixture = await createFixture()
    const { createFactProposal, writeSnapshot } = await import('../../server/utils/memoryRepository')
    const { tables } = await import('../../server/utils/drizzle')

    await writeSnapshot(fixture.db, snapshotInput(fixture))
    await createFactProposal(fixture.db, proposalInput(fixture))
    await fixture.db.delete(tables.chats).where(eq(tables.chats.id, fixture.chatId))

    const snapshots = await fixture.db.select().from(tables.memorySnapshots)
      .where(eq(tables.memorySnapshots.chatId, fixture.chatId))
    const facts = await fixture.db.select().from(tables.memoryFacts)
      .where(eq(tables.memoryFacts.chatId, fixture.chatId))

    expect(snapshots).toEqual([])
    expect(facts).toEqual([])
  })

  it('rejects a duplicate Snapshot version within one chat revision', async () => {
    const fixture = await createFixture()
    const { writeSnapshot } = await import('../../server/utils/memoryRepository')

    await writeSnapshot(fixture.db, snapshotInput(fixture))
    await expect(writeSnapshot(fixture.db, snapshotInput(fixture))).rejects.toThrow()
  })

  it('does not allow one user to bind a Fact to another users chat', async () => {
    const owner = await createFixture()
    const attacker = await createFixture()
    const { tables } = await import('../../server/utils/drizzle')
    const { MemoryRepositoryError, createFactProposal } = await import('../../server/utils/memoryRepository')

    await expect(createFactProposal(attacker.db, {
      ...proposalInput(owner),
      actorUserId: attacker.userId
    })).rejects.toBeInstanceOf(MemoryRepositoryError)

    const facts = await owner.db.select().from(tables.memoryFacts)
      .where(eq(tables.memoryFacts.chatId, owner.chatId))
    expect(facts).toEqual([])
  })

  it('clears a Fact source message reference when its source message is deleted', async () => {
    const fixture = await createFixture()
    const { tables } = await import('../../server/utils/drizzle')
    const { createFactProposal } = await import('../../server/utils/memoryRepository')
    const proposal = await createFactProposal(fixture.db, proposalInput(fixture))

    await fixture.db.delete(tables.messages).where(eq(tables.messages.id, fixture.source.id))

    const facts = await fixture.db.select().from(tables.memoryFacts)
      .where(eq(tables.memoryFacts.id, proposal.fact.id))
    expect(facts[0]?.sourceMessageId).toBeNull()
  })

  it('advances revision and makes edited history Memory-invisible in the same transaction', async () => {
    const fixture = await createFixture()
    const { appendMessage, createCurrentMessageHandoff } = await import('../../server/utils/messageLifecycle')
    const { buildPersistentMemoryContext } = await import('../../server/utils/persistentMemoryContext')
    const {
      confirmFact,
      createFactProposal,
      getActiveSnapshot,
      getVisibleFacts,
      truncateHistoryAndInvalidateMemory,
      writeSnapshot
    } = await import('../../server/utils/memoryRepository')

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
    const confirmedProposal = await createFactProposal(fixture.db, proposalInput(fixture))
    const pendingProposal = await createFactProposal(fixture.db, {
      ...proposalInput(fixture),
      category: 'GOAL',
      value: 'Finish the current task.'
    })
    await confirmFact(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      factId: confirmedProposal.fact.id,
      historyRevision: 1
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
      historyRevision: 2,
      revokedFactCount: 2
    })

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
    const oldFacts = await fixture.db.select().from((await import('../../server/utils/drizzle')).tables.memoryFacts)
      .where(eq((await import('../../server/utils/drizzle')).tables.memoryFacts.chatId, fixture.chatId))
    const context = await buildPersistentMemoryContext(
      fixture.db,
      createCurrentMessageHandoff(fixture.userId, edited)
    )

    expect(oldSnapshot).toEqual(snapshot)
    expect(newSnapshot).toBeUndefined()
    expect(oldFacts).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: confirmedProposal.fact.id, status: 'REVOKED' }),
      expect.objectContaining({ id: pendingProposal.fact.id, status: 'REVOKED' })
    ]))
    expect(await getVisibleFacts(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      historyRevision: 2
    })).toEqual([])
    expect(context).toMatchObject({ facts: [], snapshot: null, tail: [] })
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
      parts: [{ text: 'New regenerated answer.', type: 'text' }],
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
    const {
      createFactProposal,
      getActiveSnapshot,
      truncateHistoryAndInvalidateMemory,
      writeSnapshot
    } = await import('../../server/utils/memoryRepository')

    const snapshot = await writeSnapshot(fixture.db, snapshotInput(fixture))
    const proposal = await createFactProposal(fixture.db, proposalInput(fixture))
    await expect(truncateHistoryAndInvalidateMemory(fixture.db, {
      actorUserId: `attacker-${randomUUID()}`,
      chatId: fixture.chatId,
      messageId: fixture.source.id,
      type: 'edit'
    })).rejects.toMatchObject({ statusCode: 404 })

    const { tables } = await import('../../server/utils/drizzle')
    const [chat] = await fixture.db.select().from(tables.chats)
      .where(eq(tables.chats.id, fixture.chatId))
    const [fact] = await fixture.db.select().from(tables.memoryFacts)
      .where(eq(tables.memoryFacts.id, proposal.fact.id))
    expect(chat?.historyRevision).toBe(1)
    expect(fact?.status).toBe('PROPOSED')
    expect(await getActiveSnapshot(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      historyRevision: 1
    })).toEqual(snapshot)
  })

  it('keeps branch sequence and persistent Memory isolated from its parent chat', async () => {
    const fixture = await createFixture()
    const { appendMessage } = await import('../../server/utils/messageLifecycle')
    const { confirmFact, createFactProposal, getActiveSnapshot, getVisibleFacts, writeSnapshot } = await import('../../server/utils/memoryRepository')
    const { tables } = await import('../../server/utils/drizzle')
    const parentSnapshot = await writeSnapshot(fixture.db, snapshotInput(fixture))
    const proposal = await createFactProposal(fixture.db, proposalInput(fixture))
    await confirmFact(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      expiresAt: null,
      factId: proposal.fact.id,
      historyRevision: 1
    })

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
    expect(await getVisibleFacts(fixture.db, {
      actorUserId: fixture.userId,
      chatId: branchId,
      historyRevision: 1
    })).toEqual([])
    expect(await getActiveSnapshot(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      historyRevision: 1
    })).toEqual(parentSnapshot)
  })

  it('reads tail messages and applies the SESSION Fact state machine idempotently', async () => {
    const fixture = await createFixture()
    const { appendMessage } = await import('../../server/utils/messageLifecycle')
    const {
      MemoryFactRevokedError,
      archiveSnapshot,
      confirmFact,
      createFactProposal,
      deleteMemoryByChat,
      getActiveSnapshot,
      getVisibleFacts,
      readTailMessages,
      revokeFact,
      writeSnapshot
    } = await import('../../server/utils/memoryRepository')
    const tailMessage = await appendMessage(fixture.db, {
      chatId: fixture.chatId,
      id: randomUUID(),
      parts: [{ text: 'I will keep the response concise.', type: 'text' }],
      requestId: `assistant-${randomUUID()}`,
      role: 'assistant'
    })
    const snapshot = await writeSnapshot(fixture.db, snapshotInput(fixture))
    const proposal = await createFactProposal(fixture.db, proposalInput(fixture))
    const duplicate = await createFactProposal(fixture.db, proposalInput(fixture))

    expect(duplicate).toEqual({ created: false, fact: proposal.fact })

    const confirmed = await confirmFact(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      factId: proposal.fact.id,
      historyRevision: fixture.source.historyRevision
    })
    const confirmedAgain = await confirmFact(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      factId: proposal.fact.id,
      historyRevision: fixture.source.historyRevision
    })
    expect(confirmedAgain).toEqual(confirmed)

    const active = await getActiveSnapshot(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      historyRevision: fixture.source.historyRevision
    })
    const tail = await readTailMessages(fixture.db, {
      actorUserId: fixture.userId,
      afterSequence: fixture.source.sequence,
      chatId: fixture.chatId,
      historyRevision: fixture.source.historyRevision,
      limit: 8
    })
    const visibleFacts = await getVisibleFacts(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      historyRevision: fixture.source.historyRevision
    })

    expect(active).toEqual(snapshot)
    expect(tail).toEqual([expect.objectContaining({ id: tailMessage.id, sequence: tailMessage.sequence })])
    expect(visibleFacts).toEqual([confirmed])

    const revoked = await revokeFact(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      factId: proposal.fact.id,
      historyRevision: fixture.source.historyRevision
    })
    const revokedAgain = await revokeFact(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      factId: proposal.fact.id,
      historyRevision: fixture.source.historyRevision
    })
    expect(revokedAgain).toEqual(revoked)
    await expect(confirmFact(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      factId: proposal.fact.id,
      historyRevision: fixture.source.historyRevision
    })).rejects.toBeInstanceOf(MemoryFactRevokedError)
    expect(await getVisibleFacts(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      historyRevision: fixture.source.historyRevision
    })).toEqual([])

    const archived = await archiveSnapshot(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      historyRevision: fixture.source.historyRevision,
      version: snapshot.version
    })
    expect(archived).toEqual(expect.objectContaining({ status: 'ARCHIVED' }))
    expect(await getActiveSnapshot(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      historyRevision: fixture.source.historyRevision
    })).toBeUndefined()

    expect(await deleteMemoryByChat(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId
    })).toEqual({ deletedFactCount: 1, deletedSnapshotCount: 1 })
  })

  it('keeps the browser Fact reader separate from the confirmed-only resolver reader', async () => {
    const fixture = await createFixture()
    const { confirmFact, createFactProposal, getCurrentRevisionFacts, getVisibleFacts, revokeFact } = await import('../../server/utils/memoryRepository')
    const proposed = await createFactProposal(fixture.db, proposalInput(fixture))
    const confirmedProposal = await createFactProposal(fixture.db, {
      ...proposalInput(fixture),
      category: 'GOAL',
      value: 'Finish the current project.'
    })
    const confirmed = await confirmFact(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      factId: confirmedProposal.fact.id,
      historyRevision: fixture.source.historyRevision,
      now: new Date('2026-08-23T00:00:00.000Z')
    })
    const revoked = await createFactProposal(fixture.db, {
      ...proposalInput(fixture),
      category: 'PLAN_CONSTRAINT',
      value: 'Finish before Friday.'
    })
    await revokeFact(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      factId: revoked.fact.id,
      historyRevision: fixture.source.historyRevision
    })

    const input = {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      historyRevision: fixture.source.historyRevision
    }
    const expectedBrowserFacts = [proposed.fact, confirmed].sort((left, right) => (
      left.createdAt.getTime() - right.createdAt.getTime() || left.id.localeCompare(right.id)
    ))
    expect(await getCurrentRevisionFacts(fixture.db, input)).toEqual(expectedBrowserFacts)
    expect(await getVisibleFacts(fixture.db, input)).toEqual([confirmed])
  })

  it('reads a Fact source only for its owner and exact current revision', async () => {
    const fixture = await createFixture()
    const { MemoryRepositoryError, readCurrentRevisionFactSource } = await import('../../server/utils/memoryRepository')

    await expect(readCurrentRevisionFactSource(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      historyRevision: fixture.source.historyRevision,
      sourceMessageId: fixture.source.id
    })).resolves.toMatchObject({ id: fixture.source.id, role: 'user' })
    await expect(readCurrentRevisionFactSource(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      historyRevision: fixture.source.historyRevision + 1,
      sourceMessageId: fixture.source.id
    })).resolves.toBeUndefined()
    await expect(readCurrentRevisionFactSource(fixture.db, {
      actorUserId: `attacker-${randomUUID()}`,
      chatId: fixture.chatId,
      historyRevision: fixture.source.historyRevision,
      sourceMessageId: fixture.source.id
    })).rejects.toBeInstanceOf(MemoryRepositoryError)
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
