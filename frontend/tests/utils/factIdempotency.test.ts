import { randomUUID } from 'node:crypto'
import { eq } from 'drizzle-orm'
import { describe, expect, it } from 'vitest'

async function createFixture() {
  const { tables, useDrizzle } = await import('../../server/utils/drizzle')
  const { appendMessage } = await import('../../server/utils/messageLifecycle')
  const db = useDrizzle()
  const suffix = randomUUID()
  const userId = `fact-user-${suffix}`
  const chatId = `fact-chat-${suffix}`

  await db.insert(tables.users).values({
    avatar: 'https://example.test/avatar.png',
    email: `${suffix}@fact.test`,
    id: userId,
    name: 'Fact Test User',
    provider: 'github',
    providerId: userId,
    username: `fact-user-${suffix}`
  })
  await db.insert(tables.chats).values({ id: chatId, title: 'Fact test chat', userId })
  const source = await appendMessage(db, {
    chatId,
    id: randomUUID(),
    parts: [{ text: 'Remember this fact.', type: 'text' }],
    requestId: `fact-request-${suffix}`,
    role: 'user'
  })

  return { chatId, db, source, userId }
}

function proposalInput(
  fixture: Awaited<ReturnType<typeof createFixture>>,
  category: 'GOAL' | 'PREFERENCE' | 'PLAN_CONSTRAINT' = 'PREFERENCE',
  value = 'Use concise Chinese responses.'
) {
  return {
    actorUserId: fixture.userId,
    category,
    chatId: fixture.chatId,
    historyRevision: fixture.source.historyRevision,
    sourceMessageId: fixture.source.id,
    value
  }
}

describe('Fact idempotency contract', () => {
  it('normalizes only the proposal key and never revives a revoked same-source proposal', async () => {
    const fixture = await createFixture()
    const { createFactProposal, revokeFact } = await import('../../server/utils/memoryRepository')

    const created = await createFactProposal(fixture.db, proposalInput(fixture))
    const duplicate = await createFactProposal(
      fixture.db,
      proposalInput(fixture, 'PREFERENCE', '  Use\n concise   Chinese responses.  ')
    )
    expect(duplicate).toEqual({ created: false, fact: created.fact })

    const revoked = await revokeFact(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      factId: created.fact.id,
      historyRevision: fixture.source.historyRevision,
      now: new Date('2026-08-15T00:00:00.000Z')
    })
    const afterRevoke = await createFactProposal(fixture.db, proposalInput(fixture))

    expect(afterRevoke).toEqual({ created: false, fact: revoked })
  })

  it.each([
    ['GOAL', 90],
    ['PREFERENCE', 90],
    ['PLAN_CONSTRAINT', 30]
  ] as const)('calculates a %s expiry in the repository and keeps confirm idempotent', async (category, days) => {
    const fixture = await createFixture()
    const { confirmFact, createFactProposal, getVisibleFacts } = await import('../../server/utils/memoryRepository')
    const now = new Date('2026-08-15T12:34:56.000Z')
    const proposal = await createFactProposal(fixture.db, proposalInput(fixture, category))

    const confirmed = await confirmFact(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      factId: proposal.fact.id,
      historyRevision: fixture.source.historyRevision,
      now
    })
    const expectedExpiry = new Date(now.getTime() + days * 24 * 60 * 60 * 1000)
    expect(confirmed.confirmedAt).toEqual(now)
    expect(confirmed.expiresAt).toEqual(expectedExpiry)

    const confirmedAgain = await confirmFact(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      factId: proposal.fact.id,
      historyRevision: fixture.source.historyRevision,
      now: new Date('2099-01-01T00:00:00.000Z')
    })
    expect(confirmedAgain).toEqual(confirmed)
    expect(await getVisibleFacts(fixture.db, {
      actorUserId: fixture.userId,
      chatId: fixture.chatId,
      historyRevision: fixture.source.historyRevision,
      now: expectedExpiry
    })).toEqual([])
  })

  it('makes concurrent duplicate proposals converge to one row and hides another users Fact id', async () => {
    const owner = await createFixture()
    const attacker = await createFixture()
    const { tables } = await import('../../server/utils/drizzle')
    const { MemoryRepositoryError, confirmFact, createFactProposal } = await import('../../server/utils/memoryRepository')

    const [first, second] = await Promise.all([
      createFactProposal(owner.db, proposalInput(owner)),
      createFactProposal(owner.db, proposalInput(owner))
    ])
    expect([first.created, second.created].filter(Boolean)).toHaveLength(1)
    expect(first.fact.id).toBe(second.fact.id)
    const rows = await owner.db.select().from(tables.memoryFacts)
      .where(eq(tables.memoryFacts.chatId, owner.chatId))
    expect(rows).toHaveLength(1)

    await expect(confirmFact(attacker.db, {
      actorUserId: attacker.userId,
      chatId: attacker.chatId,
      factId: first.fact.id,
      historyRevision: attacker.source.historyRevision
    })).rejects.toBeInstanceOf(MemoryRepositoryError)
  })
})
