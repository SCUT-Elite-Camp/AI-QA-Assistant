import { and, eq } from 'drizzle-orm'
import { defineHandler, HTTPError } from 'nitro'
import { readValidatedBody } from 'nitro/h3'
import { z } from 'zod'
import { createHash } from 'node:crypto'
import { requireCsrf } from '../../../utils/attachmentAuth'
import { requireResearchActor, fetchResearchBackend } from '../../../utils/researchBackend'
import { accessBackend, assertMessageSources, assertSourceDependencies, provenancePart, type SourceDependency } from '../../../utils/sourceAccess'
import { appendMessage } from '../../../utils/messageLifecycle'
import { tables, useDrizzle } from '../../../utils/drizzle'

export default defineHandler(async (event) => {
  requireCsrf(event)
  const body = await readValidatedBody(event, z.object({
    chatId: z.string().regex(/^research-[a-zA-Z0-9]+$/),
    messageId: z.string().min(1).max(160),
    text: z.string().min(1),
    createdAt: z.string().datetime().optional(),
  }).parse)
  const db = useDrizzle()
  const userId = await requireResearchActor(event)
  const chat = await db.query.chats.findFirst({
    where: and(eq(tables.chats.id, body.chatId), eq(tables.chats.userId, userId)),
  })
  if (!chat) throw new HTTPError({ statusCode: 404, statusMessage: 'Research conversation not found' })

  const existing = await db.query.messages.findFirst({
    where: and(eq(tables.messages.id, body.messageId), eq(tables.messages.chatId, body.chatId)),
  })
  const jobResponse = await fetchResearchBackend(userId, `jobs/${body.chatId}`)
  if (!jobResponse.ok) throw new HTTPError({ statusCode: jobResponse.status, statusMessage: 'Research job unavailable' })
  const job = await jobResponse.json() as { request: { source_scope: { document_ids: string[] } } }
  const reportResponse = await fetchResearchBackend(userId, `jobs/${body.chatId}/report`)
  const report = reportResponse.ok ? await reportResponse.json() as any : null
  let canonical: string | undefined = report?.markdown === body.text ? report.markdown : undefined
  if (!canonical) {
    let cursor = 0
    for (let page = 0; page < 10 && !canonical; page++) {
      const eventsResponse = await fetchResearchBackend(userId, `jobs/${body.chatId}/events`, { search: `?after_event_id=${cursor}&limit=100` })
      if (!eventsResponse.ok) throw new HTTPError({ statusCode: eventsResponse.status, statusMessage: 'Research transcript unavailable' })
      const events = await eventsResponse.json() as { events: any[] }
      canonical = events.events.filter(item => item.event_type === 'assistant_message')
        .map(item => item.payload?.content || item.message).find(text => text === body.text)
      if (events.events.length < 100) break
      cursor = Number(events.events.at(-1)?.event_id)
      if (!Number.isSafeInteger(cursor) || cursor < 1) break
    }
  }
  if (!canonical) throw new HTTPError({ statusCode: 400, statusMessage: 'Unverified Research text' })
  if (existing) { await assertMessageSources(userId, existing); return existing }
  const catalogResponse = await fetchResearchBackend(userId, 'documents')
  if (!catalogResponse.ok) throw new HTTPError({ statusCode: catalogResponse.status, statusMessage: 'Research sources unavailable' })
  const catalog = await catalogResponse.json() as any[]
  const dependencies: SourceDependency[] = job.request.source_scope.document_ids.map(docId => {
    const source = catalog.find(item => item.doc_id === docId)
    if (!source?.content_hash) throw new HTTPError({ statusCode: 409, statusMessage: 'Source version unavailable' })
    return { source_type: 'knowledge', doc_id: docId, version: source.version, content_hash: source.content_hash }
  })
  await assertSourceDependencies(userId, dependencies)
  const citations = []
  for (const citation of report?.citations || []) {
    const dependency = dependencies.find(item => item.doc_id === citation.doc_id)
    if (!dependency?.content_hash) throw new HTTPError({ statusCode: 409, statusMessage: 'Unbound Research citation' })
    const source = await (await accessBackend(userId, `documents/${encodeURIComponent(citation.doc_id)}/source?expected_hash=${encodeURIComponent(dependency.content_hash)}`)).json() as any
    const normalized = (value: unknown) => String(value || '').replace(/\s+/g, ' ').trim()
    if (!normalized(citation.excerpt) || !normalized(source.content).includes(normalized(citation.excerpt))) {
      throw new HTTPError({ statusCode: 409, statusMessage: 'Research evidence changed' })
    }
    citations.push({
      citation_id: citation.number, index: citation.number, doc_id: citation.doc_id,
      title: source.title, source_type: 'knowledge', source_url: source.source_url,
      chunk_id: citation.locator, locator: citation.locator, snippet: citation.excerpt, chunk_text: citation.excerpt,
      content_hash: dependency.content_hash, normalized_content_hash: citation.content_hash,
      source_version: dependency.version, evidence_id: citation.evidence_id, read_status: 'original_excerpt_loaded',
      evidence_ref: 'ev_' + createHash('sha256').update(`${body.chatId}:${citation.evidence_id}:${dependency.content_hash}`).digest('hex').slice(0, 32),
    })
  }
  await assertSourceDependencies(userId, dependencies)

  return appendMessage(db, {
    id: body.messageId,
    chatId: body.chatId,
    role: 'assistant',
    requestId: body.messageId,
    parts: [{ type: 'text', text: canonical }, { type: 'tool-rag_search', state: 'output-available', toolCallId: body.messageId, input: {}, output: citations },
      provenancePart({ schema_version: 'evidence.provenance.v1', complete: true, dependencies })],
  })
})
