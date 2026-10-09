import { and, eq } from 'drizzle-orm'
import { defineHandler, HTTPError } from 'nitro'
import { getQuery } from 'nitro/h3'
import { requirePrincipal } from '../../../utils/attachmentAuth'
import { tables, useDrizzle } from '../../../utils/drizzle'
import { getAgentBaseUrl } from '../../../utils/agentConfig'

export default defineHandler(async (event) => {
  const userId = await requirePrincipal(event)
  const researchId = String(getQuery(event).researchId ?? '')
  if (!/^research-[a-zA-Z0-9]+$/.test(researchId)) {
    throw new HTTPError({ statusCode: 400, statusMessage: 'Invalid research identifier' })
  }
  const chat = await useDrizzle().query.chats.findFirst({
    where: and(eq(tables.chats.id, researchId), eq(tables.chats.userId, userId)),
  })
  if (!chat) throw new HTTPError({ statusCode: 404, statusMessage: 'Research conversation not found' })
  const token = process.env.AGENT_API_KEY?.trim()
  if (!token) throw new HTTPError({ statusCode: 503, statusMessage: 'Agent configuration unavailable' })
  const response = await fetch(`${getAgentBaseUrl()}/api/research/jobs/${encodeURIComponent(researchId)}/report`, {
    headers: { Authorization: `Bearer ${token}`, 'X-User-ID': userId },
    signal: AbortSignal.timeout(15000),
  })
  if (!response.ok) throw new HTTPError({ statusCode: response.status, statusMessage: 'Research report unavailable' })
  const report = await response.json() as { report_id?: unknown, markdown?: unknown }
  if (typeof report.markdown !== 'string') {
    throw new HTTPError({ statusCode: 502, statusMessage: 'Invalid research report' })
  }
  const filename = String(report.report_id ?? researchId).replace(/[^a-zA-Z0-9_-]/g, '_')
  return new Response(report.markdown, { headers: {
    'content-type': 'text/markdown; charset=utf-8',
    'content-disposition': `attachment; filename="${filename}.md"`,
    'cache-control': 'private, no-store',
    'x-content-type-options': 'nosniff',
  } })
})
