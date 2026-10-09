import { defineHandler } from 'nitro'
import { readValidatedBody } from 'nitro/h3'
import { z } from 'zod'
import { requireCsrf, requirePrincipal } from '../../../utils/attachmentAuth'
import { registerResearchChat } from '../../../utils/researchChat'
import { useDrizzle } from '../../../utils/drizzle'

export default defineHandler(async (event) => {
  requireCsrf(event)
  const { researchId, query } = await readValidatedBody(event, z.object({
    researchId: z.string().regex(/^research-[a-zA-Z0-9]+$/),
    query: z.string().trim().min(1).max(4000),
  }).parse)
  return registerResearchChat(useDrizzle(), researchId, query, await requirePrincipal(event))
})
