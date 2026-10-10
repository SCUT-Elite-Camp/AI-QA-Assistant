import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { HTTPEvent } from 'nitro/h3'
const fixture = vi.hoisted(() => ({ body: {} as Record<string, unknown>, backend: vi.fn() }))
vi.mock('nitro', async original => ({ ...await original<object>(), defineHandler: (handler: unknown) => handler }))
vi.mock('nitro/h3', async original => ({ ...await original<object>(), readValidatedBody: async () => fixture.body }))
vi.mock('../server/utils/attachmentAuth', () => ({ requireCsrf: vi.fn() }))
vi.mock('../server/utils/researchBackend', () => ({ requireResearchActor: async () => 'alice', fetchResearchBackend: fixture.backend }))
vi.mock('../server/utils/sourceAccess', async original => ({ ...await original<object>(), assertSourceDependencies: vi.fn() }))
import register from '../server/routes/api/research/chats.post'
import persist from '../server/routes/api/research/messages.post'
import { tables, useDrizzle, eq } from '../server/utils/drizzle'

beforeEach(() => {
  fixture.backend.mockImplementation(async (_actor, path: string) => new Response(JSON.stringify(
    path === 'documents' ? [] : path.endsWith('/events') ? { events: [] } : path.endsWith('/report')
      ? { markdown: '# Verified answer [1]' } : { request: { query: 'Authoritative question', source_scope: { document_ids: [] } } },
  ), { status: 200 }))
})

describe('Research transcript persistence with current message schema', () => {
  it('registers idempotently and allocates a valid user-message sequence', async () => {
    fixture.body = { researchId: 'research-persist1', query: 'Browser supplied text' }
    await Promise.all([register({} as HTTPEvent), register({} as HTTPEvent)])
    const messages = await useDrizzle().select().from(tables.messages).where(eq(tables.messages.chatId, 'research-persist1'))
    expect(messages).toHaveLength(1)
    expect(messages[0]).toMatchObject({ role: 'user', sequence: 1, historyRevision: 1 })
    expect(messages[0]!.parts).toEqual(expect.arrayContaining([{ type: 'text', text: 'Authoritative question' },
      expect.objectContaining({ type: 'data-evidence-provenance' })]))
  })
  it('persists only a server-verified answer with a stable second sequence', async () => {
    fixture.body = { researchId: 'research-persist2', query: 'Question' }
    await register({} as HTTPEvent)
    fixture.body = { chatId: 'research-persist2', messageId: 'report-persist2', text: 'Invented answer' }
    await expect(persist({} as HTTPEvent)).rejects.toMatchObject({ status: 400 })
    fixture.body.text = '# Verified answer [1]'
    await Promise.all([persist({} as HTTPEvent), persist({} as HTTPEvent)])
    const messages = await useDrizzle().select().from(tables.messages).where(eq(tables.messages.chatId, 'research-persist2'))
    expect(messages).toHaveLength(2)
    const assistant = messages.find(item => item.role === 'assistant')
    expect(assistant).toMatchObject({ sequence: 2, historyRevision: 1, requestId: 'report-persist2' })
  })
})
