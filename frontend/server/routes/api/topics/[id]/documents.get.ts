import { z } from 'zod'
import { defineHandler } from 'nitro'
import { getValidatedRouterParams } from 'nitro/h3'
import { useDrizzle, tables, eq, and } from '../../../../utils/drizzle'
import { requireTopicRole } from '../../../../utils/attachmentAuth'
import { readableTopicDocuments } from '../../../../utils/topicEvidence'

export default defineHandler(async (event) => {
  const { id } = await getValidatedRouterParams(event, z.object({ id: z.string() }).parse)
  const { userId } = await requireTopicRole(event, id, 'viewer')
  const docs = await useDrizzle().query.topicDocuments.findMany({ where: and(
    eq(tables.topicDocuments.topicId, id), eq(tables.topicDocuments.isRemoved, false),
  ) })
  const readable = await readableTopicDocuments(userId, docs)
  return readable.sort((a, b) => (b.recallCount || 0) - (a.recallCount || 0))
})
