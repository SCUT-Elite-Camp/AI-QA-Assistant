import { eq, inArray, tables, useDrizzle } from './drizzle'
import { attachmentServiceFetch } from './attachmentService'

export async function cleanupOrphanedAttachments(attachmentIds: string[]): Promise<void> {
  const ids = Array.from(new Set(attachmentIds))
  if (!ids.length) return
  const db = useDrizzle()
  const candidates = await db.query.attachments.findMany({ where: inArray(tables.attachments.id, ids) })
  for (const attachment of candidates) {
    if (attachment.scope === 'topic' || attachment.deletedAt) continue
    const reference = await db.query.messageAttachments.findFirst({ where: eq(tables.messageAttachments.attachmentId, attachment.id) })
    if (reference) continue
    await db.update(tables.attachments).set({ status: 'deleted', deletedAt: new Date() }).where(eq(tables.attachments.id, attachment.id))
    await attachmentServiceFetch(`/v1/attachments/${attachment.id}`, { method: 'DELETE' }).catch(() => undefined)
  }
}
