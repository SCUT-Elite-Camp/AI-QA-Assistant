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
      expiresAt: null,
      factId: proposal.fact.id,
      historyRevision: fixture.source.historyRevision
    })
    const confirmedAgain = await confirmFact(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      expiresAt: new Date('2099-01-01T00:00:00.000Z'),
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
      expiresAt: null,
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
})
