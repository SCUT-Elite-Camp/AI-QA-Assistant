import { eq, tables, useDrizzle } from './drizzle'

/** Register the initial question atomically and reuse the conversation on retries. */
export async function registerResearchChat(db: ReturnType<typeof useDrizzle>, researchId: string, query: string, userId: string) {
  return db.transaction(async (tx) => {
    await tx.insert(tables.chats).values({
      id: researchId,
      title: query.length > 28 ? `${query.slice(0, 28)}...` : query,
      userId,
      historyRevision: 1,
      nextMessageSequence: 2,
    }).onConflictDoNothing()
    const [chat] = await tx.select().from(tables.chats).where(eq(tables.chats.id, researchId))
    if (!chat || chat.userId !== userId) throw new Error('Research conversation is unavailable')
    await tx.insert(tables.messages).values({
      chatId: researchId,
      role: 'user',
      sequence: 1,
      historyRevision: 1,
      parts: [{ type: 'text', text: query }],
    }).onConflictDoNothing()
    if (chat.nextMessageSequence < 2) {
      const [repaired] = await tx.update(tables.chats).set({ nextMessageSequence: 2 }).where(eq(tables.chats.id, researchId)).returning()
      return repaired ?? chat
    }
    return chat
  })
}
