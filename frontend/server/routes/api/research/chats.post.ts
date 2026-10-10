import { defineHandler } from 'nitro'
import { readValidatedBody } from 'nitro/h3'
import { z } from 'zod'
import { requireCsrf } from '../../../utils/attachmentAuth'
import { requireResearchActor, fetchResearchBackend } from '../../../utils/researchBackend'
import { HTTPError } from 'nitro'
import { registerResearchChat } from '../../../utils/researchChat'
import { useDrizzle } from '../../../utils/drizzle'

export default defineHandler(async (event) => {
  requireCsrf(event)
  const { researchId, query } = await readValidatedBody(event, z.object({
    researchId: z.string().regex(/^research-[a-zA-Z0-9]+$/),
    query: z.string().trim().min(1).max(4000),
  }).parse)
  const userId = await requireResearchActor(event)
  const response = await fetchResearchBackend(userId, `jobs/${researchId}`)
  if (!response.ok) throw new HTTPError({ statusCode: response.status, statusMessage: 'Research conversation unavailable' })
  const job = await response.json() as { request?: { query?: string } }
  if (!job.request?.query) throw new HTTPError({ statusCode: 502, statusMessage: 'Invalid Research job' })
  return registerResearchChat(useDrizzle(), researchId, job.request.query, userId)
})
