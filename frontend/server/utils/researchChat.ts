import { eq, tables, useDrizzle } from './drizzle'
import { authoredProvenance } from './sourceAccess'
const registrations = new Map<string, Promise<unknown>>()

/** Register the initial question atomically and reuse the conversation on retries. */
export async function registerResearchChat(db: ReturnType<typeof useDrizzle>, researchId: string, query: string, userId: string) {
  const previous = registrations.get(researchId) ?? Promise.resolve()
  const registration = previous.catch(() => undefined).then(() => register(db, researchId, query, userId))
  registrations.set(researchId, registration)
  try { return await registration } finally { if (registrations.get(researchId) === registration) registrations.delete(researchId) }
}

async function register(db: ReturnType<typeof useDrizzle>, researchId: string, query: string, userId: string) {
  return db.transaction(async (tx) => {
    await tx.insert(tables.chats).values({
      id: researchId,
      title: query.length > 28 ? `${query.slice(0, 28)}...` : query,
      userId,
      historyRevision: 1,
      nextMessageSequence: 2,
      evidenceProvenance: authoredProvenance(),
    }).onConflictDoNothing()
    const [chat] = await tx.select().from(tables.chats).where(eq(tables.chats.id, researchId))
    if (!chat || chat.userId !== userId) throw new Error('Research conversation is unavailable')
    await tx.insert(tables.messages).values({
      chatId: researchId,
      role: 'user',
      sequence: 1,
      historyRevision: 1,
      parts: [{ type: 'text', text: query }, { type: 'data-evidence-provenance', data: {
        schema_version: 'evidence.provenance.v1', complete: true, dependencies: [],
      } }],
    }).onConflictDoNothing()
    if (chat.nextMessageSequence < 2) {
      const [repaired] = await tx.update(tables.chats).set({ nextMessageSequence: 2 }).where(eq(tables.chats.id, researchId)).returning()
      return repaired ?? chat
    }
    return chat
  })
}
