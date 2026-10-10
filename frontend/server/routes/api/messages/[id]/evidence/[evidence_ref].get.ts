import { defineHandler, HTTPError } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { eq, tables, useDrizzle } from '../../../../../utils/drizzle'
import { requireOwnedChat } from '../../../../../utils/chatAccess'
import { accessBackend, assertMessageSources } from '../../../../../utils/sourceAccess'
import { attachmentServiceJson } from '../../../../../utils/attachmentService'

export default defineHandler(async (event) => {
  const id = getRouterParam(event, 'id', { decode: true }) || ''
  const reference = getRouterParam(event, 'evidence_ref', { decode: true }) || ''
  const message = await useDrizzle().query.messages.findFirst({ where: eq(tables.messages.id, id) })
  if (!message) throw new HTTPError({ statusCode: 404, statusMessage: 'message_not_found' })
  const { actor } = await requireOwnedChat(event, message.chatId)
  await assertMessageSources(actor.userId, message)
  const parts = Array.isArray(message.parts) ? message.parts : []
  const citations = parts.flatMap((part: any) => part?.type === 'tool-rag_search' && Array.isArray(part.output) ? part.output : [])
  const evidence = citations.find((citation: any) => citation.evidence_ref === reference)
  if (!evidence) throw new HTTPError({ statusCode: 404, statusMessage: 'evidence_not_found' })
  let source: any
  if (!evidence.source_type || evidence.source_type === 'knowledge') {
    if (!evidence.content_hash) {
      throw new HTTPError({ statusCode: 409, statusMessage: 'source_provenance_incomplete' })
    }
    const params = new URLSearchParams({ expected_hash: evidence.content_hash })
    if (evidence.source_version || evidence.version) params.set('expected_version', String(evidence.source_version || evidence.version))
    source = await (await accessBackend(actor.userId, `documents/${encodeURIComponent(evidence.doc_id)}/source?${params}`)).json()
    const content = String(source.content || '')
    const excerpt = String(evidence.snippet || evidence.chunk_text || '')
    const normalized = (value: string) => value.replace(/\s+/g, ' ').trim()
    if (!normalized(excerpt) || !normalized(content).includes(normalized(excerpt))) throw new HTTPError({ statusCode: 409, statusMessage: 'source_evidence_changed' })
  } else {
    let storageId = evidence.attachment_id
    if (evidence.source_type === 'personal') {
      const version = await useDrizzle().query.documentVersions.findFirst({ where: eq(tables.documentVersions.id, evidence.version_id) })
      storageId = version?.storageRef
    }
    if (!storageId) throw new HTTPError({ statusCode: 409, statusMessage: 'source_provenance_incomplete' })
    const data = await attachmentServiceJson<any>(`/v1/attachments/${encodeURIComponent(storageId)}/evidence`)
    const item = data.items?.find((candidate: any) => candidate.evidence_id === evidence.evidence_id)
    if (!item || (evidence.source_version != null && String(item.source_version) !== String(evidence.source_version))
      || String(item.content).trim() !== String(evidence.snippet || evidence.chunk_text).trim()) {
      throw new HTTPError({ statusCode: 409, statusMessage: 'source_evidence_changed' })
    }
    source = { content: item.content, read_status: 'evidence_only', locator: item.locator }
  }
  await assertMessageSources(actor.userId, message)
  return Response.json({ evidence, source, access: 'allowed' }, { headers: { 'Cache-Control': 'private, no-store' } })
})
