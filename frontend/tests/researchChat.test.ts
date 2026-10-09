import { describe, expect, it } from 'vitest'
import { eq, tables, useDrizzle } from '../server/utils/drizzle'
import { registerResearchChat } from '../server/utils/researchChat'

describe('research conversation registration', () => {
  it('persists a sequenced question and reuses it on retries', async () => {
    const db = useDrizzle()
    const id = `research-${crypto.randomUUID().replaceAll('-', '')}`
    await registerResearchChat(db, id, 'Compare W30 and W34 Agent deliveries.', 'test-user')
    await registerResearchChat(db, id, 'Compare W30 and W34 Agent deliveries.', 'test-user')
    const messages = await db.select().from(tables.messages).where(eq(tables.messages.chatId, id))
    expect(messages).toHaveLength(1)
    expect(messages[0]).toMatchObject({ sequence: 1, historyRevision: 1, role: 'user' })
    const [chat] = await db.select().from(tables.chats).where(eq(tables.chats.id, id))
    expect(chat?.nextMessageSequence).toBe(2)
  })

  it('rejects another user without modifying an existing conversation', async () => {
    const db = useDrizzle()
    const id = `research-${crypto.randomUUID().replaceAll('-', '')}`
    await registerResearchChat(db, id, 'Original question', 'owner')
    await expect(registerResearchChat(db, id, 'Replaced question', 'other')).rejects.toThrow('unavailable')
    const messages = await db.select().from(tables.messages).where(eq(tables.messages.chatId, id))
    expect(messages).toHaveLength(1)
    expect(messages[0]?.parts).toEqual([{ type: 'text', text: 'Original question' }])
  })

  it('repairs a partially registered conversation before saving its report', async () => {
    const db = useDrizzle()
    const id = `research-${crypto.randomUUID().replaceAll('-', '')}`
    await db.insert(tables.chats).values({ id, title: 'Interrupted registration', userId: 'test-user' })
    await registerResearchChat(db, id, 'Original question', 'test-user')
    const { appendMessage } = await import('../server/utils/messageLifecycle')
    const report = await appendMessage(db, { chatId: id, role: 'assistant', parts: [{ type: 'text', text: 'Verified report [1]' }] })
    expect(report.sequence).toBe(2)
  })

  it('migrates the account tables required for login and settings', async () => {
    const db = useDrizzle()
    for (const table of [tables.departments, tables.userDepartments, tables.userSettings, tables.filePermissions, tables.auditLogs]) {
      await expect(db.select().from(table).limit(1)).resolves.toEqual([])
    }
  })
})
