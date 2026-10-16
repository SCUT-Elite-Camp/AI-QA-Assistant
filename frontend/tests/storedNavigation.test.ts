import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ userId: 'alice' as string | undefined, agent: vi.fn(), private: vi.fn() }))
vi.mock('nitro', async original => ({ ...await original<object>(), defineHandler: (handler: unknown) => handler }))
vi.mock('nitro/h3', async original => ({ ...await original<object>(),
  getValidatedRouterParams: async (event: any, parse: (value: unknown) => unknown) => parse({ id: event.testId }),
}))
vi.mock('../server/utils/session', () => ({ useUserSession: async () => ({ data: { user: mocks.userId ? { id: mocks.userId } : undefined } }) }))
vi.mock('../server/utils/agent-client', () => ({ agentFetch: mocks.agent }))
vi.mock('../server/utils/attachmentService', () => ({ attachmentServiceJson: mocks.private }))

import { eq, tables, useDrizzle } from '../server/utils/drizzle'
import chats from '../server/routes/api/chats.get'
import chat from '../server/routes/api/chats/[id].get'
import topics from '../server/routes/api/topics.get'
import topic from '../server/routes/api/topics/[id].get'
import documents from '../server/routes/api/topics/[id]/documents.get'
import dialogues from '../server/routes/api/topics/[id]/dialogues.get'
import favorites from '../server/routes/api/chats/favorites.get'

const read = (handler: unknown, testId?: string): Promise<any> => (handler as any)({ testId })
const proof = { schema_version: 'evidence.provenance.v1' as const, complete: true,
  dependencies: [{ source_type: 'knowledge' as const, doc_id: 'removed-source', version: 1, content_hash: 'old-hash' }] }

beforeAll(async () => {
  const db = useDrizzle()
  for (const id of ['alice', 'bob', 'disabled']) await db.insert(tables.users).values({ id, providerId: id, provider: 'github',
    email: id + '@test.invalid', name: id, username: id, avatar: '', disabled: id === 'disabled' })
  await db.insert(tables.topics).values({ id: 'topic', title: 'Saved topic', mainChatId: 'topic-chat',
    soulContent: 'Saved summary', evidenceProvenance: proof })
  await db.insert(tables.topicMembers).values({ topicId: 'topic', userId: 'alice', role: 'owner' })
  await db.insert(tables.chats).values([
    { id: 'topic-chat', userId: 'alice', topicId: 'topic', title: 'Saved topic chat', evidenceProvenance: proof },
    { id: 'private-chat', userId: 'alice', title: 'Saved private chat', evidenceProvenance: proof },
    { id: 'bob-chat', userId: 'bob', title: 'Bob private chat' },
  ])
  for (const id of ['topic-chat', 'private-chat']) await db.insert(tables.messages).values({ id: id + '-answer', chatId: id,
    role: 'assistant', sequence: 1, historyRevision: 1, isFavorite: true,
    parts: [{ type: 'text', text: 'Saved answer' }, { type: 'data-evidence-provenance', data: proof }] })
  await db.insert(tables.topicDocuments).values({ id: 'pool-doc', topicId: 'topic', docId: 'removed-source',
    title: 'Saved document title', snippet: 'Saved document excerpt', isUserUploaded: true })
})
beforeEach(() => {
  mocks.userId = 'alice'
  mocks.agent.mockReset().mockRejectedValue(new Error('source offline'))
  mocks.private.mockReset().mockRejectedValue(new Error('source offline'))
})

describe('saved navigation does not revalidate source snapshots', () => {
  it('reads stored lists, transcripts, topic summaries, documents and favorites with source services offline', async () => {
    expect((await read(chats)).map((item: any) => item.id).sort()).toEqual(['private-chat', 'topic-chat'])
    const saved = await read(chat, 'private-chat')
    expect(saved.title).toBe('Saved private chat')
    expect(saved.messages[0].parts[0].text).toBe('Saved answer')
    expect((await read(topics))[0].title).toBe('Saved topic')
    const savedTopic = await read(topic, 'topic')
    expect(savedTopic.soulContent).toBe('Saved summary')
    expect(savedTopic.documents[0].title).toBe('Saved document title')
    expect((await read(documents, 'topic'))[0].snippet).toBe('Saved document excerpt')
    expect((await read(dialogues, 'topic')).mainChat.messages[0].parts[0].text).toBe('Saved answer')
    expect((await read(favorites)).map((item: any) => item.title).sort()).toEqual(['Saved private chat', 'Saved topic chat'])
    expect(mocks.agent).not.toHaveBeenCalled()
    expect(mocks.private).not.toHaveBeenCalled()
  })
  it('still enforces private chat ownership and current topic membership', async () => {
    mocks.userId = 'bob'
    expect((await read(chats)).map((item: any) => item.id)).toEqual(['bob-chat'])
    expect(await read(topics)).toEqual([])
    await expect(read(chat, 'private-chat')).rejects.toMatchObject({ status: 404 })
    for (const handler of [chat, topic, documents, dialogues]) {
      await expect(read(handler, handler === chat ? 'topic-chat' : 'topic')).rejects.toMatchObject({ status: 403 })
    }
  })
  it('does not bypass a removed membership for the original chat creator', async () => {
    const db = useDrizzle()
    await db.delete(tables.topicMembers).where(eq(tables.topicMembers.userId, 'alice'))
    try {
      await expect(read(chat, 'topic-chat')).rejects.toMatchObject({ status: 403 })
      expect((await read(favorites)).map((item: any) => item.id)).toEqual(['private-chat'])
    } finally {
      await db.insert(tables.topicMembers).values({ topicId: 'topic', userId: 'alice', role: 'owner' })
    }
  })
  it.each([undefined, 'disabled'])('rejects missing or disabled local identity: %s', async userId => {
    mocks.userId = userId
    await expect(read(chats)).rejects.toMatchObject({ status: userId ? 403 : 401 })
    await expect(read(chat, 'private-chat')).rejects.toMatchObject({ status: userId ? 403 : 401 })
  })
})
