import { HTTPError } from 'nitro'
import type { HTTPEvent } from 'nitro/h3'
import { useUserSession } from './session'
import { and, eq, tables, useDrizzle } from './drizzle'
import { agentFetch } from './agent-client'
import { attachmentServiceJson } from './attachmentService'
import { sourceDependencySchema, evidenceProvenanceSchema, type EvidenceProvenance, type SourceDependency } from './evidenceContract'
export { sourceDependencySchema, evidenceProvenanceSchema, type EvidenceProvenance, type SourceDependency } from './evidenceContract'

export async function requireEnabledActor(event: HTTPEvent): Promise<string> {
  const userId = (await useUserSession(event)).data.user?.id
  if (!userId) throw new HTTPError({ statusCode: 401, statusMessage: 'login_required' })
  const user = await useDrizzle().query.users.findFirst({ where: eq(tables.users.id, userId) })
  if (!user) throw new HTTPError({ statusCode: 401, statusMessage: 'login_required' })
  if (user.disabled) throw new HTTPError({ statusCode: 403, statusMessage: 'user_disabled' })
  return userId
}

export async function requireAdministrator(event: HTTPEvent): Promise<string> {
  const userId = await requireEnabledActor(event)
  const user = await useDrizzle().query.users.findFirst({ where: eq(tables.users.id, userId) })
  if (user?.role !== 'admin') throw new HTTPError({ statusCode: 403, statusMessage: 'administrator_required' })
  return userId
}

export async function accessBackend(userId: string, path: string, options: RequestInit = {}): Promise<Response> {
  let response: Response
  try { response = await agentFetch(`/api/access/${path}`, {
    ...options, redirect: 'error', headers: { 'X-User-ID': userId, 'Content-Type': 'application/json' },
  }) } catch { throw new HTTPError({ statusCode: 503, statusMessage: 'source_access_unavailable' }) }
  if (!response.ok) throw new HTTPError({ statusCode: response.status, statusMessage: 'source_access_unavailable' })
  return response
}

/** Current access, never the permissions captured when a response was created. */
export async function assertSourceDependencies(userId: string, dependencies: SourceDependency[]): Promise<void> {
  const enterprise = [...new Set(dependencies.filter(d => d.source_type === 'knowledge').map(d => d.doc_id))]
  if (enterprise.length) {
    const response = await accessBackend(userId, 'check', { method: 'POST', body: JSON.stringify({ doc_ids: enterprise }) })
    const result = await response.json() as { allowed_doc_ids?: string[], denied_doc_ids?: string[] }
    const allowed = new Set(result.allowed_doc_ids ?? [])
    if (result.denied_doc_ids?.length || enterprise.some(id => !allowed.has(id))) {
      throw new HTTPError({ statusCode: 403, statusMessage: 'source_access_revoked' })
    }
    const sources = [...new Map(dependencies.filter(item => item.source_type === 'knowledge')
      .map(item => [JSON.stringify([item.doc_id, item.version, item.content_hash]), item])).values()]
    // Independent live source reads share only this boundary, never a cached grant.
    // Bound concurrency so a streaming batch does not serialize all source calls.
    for (let offset = 0; offset < sources.length; offset += 8) {
      await Promise.all(sources.slice(offset, offset + 8).map(async dependency => {
        if (!dependency.content_hash) throw new HTTPError({ statusCode: 409, statusMessage: 'source_provenance_incomplete' })
        const params = new URLSearchParams({ expected_hash: dependency.content_hash })
        if (dependency.version != null) params.set('expected_version', String(dependency.version))
        await accessBackend(userId, `documents/${encodeURIComponent(dependency.doc_id)}/source?${params}`)
      }))
    }
  }
  const db = useDrizzle()
  for (const dependency of dependencies.filter(d => d.source_type !== 'knowledge')) {
    if (dependency.source_type === 'personal') {
      if (!dependency.knowledge_base_id || !dependency.document_id || !dependency.version_id || !dependency.content_hash) {
        throw new HTTPError({ statusCode: 409, statusMessage: 'source_provenance_incomplete' })
      }
      const library = await db.query.knowledgeBases.findFirst({ where: and(
        eq(tables.knowledgeBases.id, dependency.knowledge_base_id), eq(tables.knowledgeBases.ownerUserId, userId),
      ) })
      const document = await db.query.libraryDocuments.findFirst({ where: and(
        eq(tables.libraryDocuments.id, dependency.document_id), eq(tables.libraryDocuments.knowledgeBaseId, dependency.knowledge_base_id),
        eq(tables.libraryDocuments.ownerUserId, userId), eq(tables.libraryDocuments.sourceScope, 'personal'),
      ) })
      const version = await db.query.documentVersions.findFirst({ where: and(
        eq(tables.documentVersions.id, dependency.version_id), eq(tables.documentVersions.documentId, dependency.document_id),
      ) })
      if (!library || library.deletedAt || !document || document.deletedAt || !version || version.status !== 'READY'
        || document.activeVersionId !== dependency.version_id
        || (dependency.content_hash && dependency.content_hash !== version.contentHash)) {
        throw new HTTPError({ statusCode: 403, statusMessage: 'source_access_revoked' })
      }
      const remote = await attachmentServiceJson<any>(`/v1/attachments/${encodeURIComponent(version.storageRef)}`)
      if (remote.sha256 !== dependency.content_hash || remote.owner_id !== userId || remote.knowledge_base_id !== dependency.knowledge_base_id
        || remote.document_id !== dependency.document_id || remote.version_id !== dependency.version_id
        || remote.scope !== 'library' || remote.source_scope !== 'personal' || !remote.active || !['ready', 'needs_review'].includes(remote.status)) {
        throw new HTTPError({ statusCode: 403, statusMessage: 'source_access_revoked' })
      }
    } else {
      const id = dependency.attachment_id || dependency.doc_id.replace(/^attachment[:_]/, '')
      const attachment = await db.query.attachments.findFirst({ where: eq(tables.attachments.id, id) })
      if (!attachment || attachment.deletedAt || !['ready', 'needs_review'].includes(attachment.status)
        || (attachment.scope !== 'topic' && attachment.expiresAt && attachment.expiresAt.getTime() <= Date.now())) {
        throw new HTTPError({ statusCode: 403, statusMessage: 'source_access_revoked' })
      }
      if (attachment.topicId) {
        const member = await db.query.topicMembers.findFirst({ where: and(
          eq(tables.topicMembers.topicId, attachment.topicId), eq(tables.topicMembers.userId, userId),
        ) })
        if (!member) throw new HTTPError({ statusCode: 403, statusMessage: 'source_access_revoked' })
      } else if (attachment.ownerId !== userId) throw new HTTPError({ statusCode: 403, statusMessage: 'source_access_revoked' })
      const remote = await attachmentServiceJson<any>(`/v1/attachments/${encodeURIComponent(id)}`)
      if (remote.owner_id !== attachment.ownerId || remote.scope !== attachment.scope
        || !['ready', 'needs_review'].includes(remote.status)
        || Number(remote.evidence_version) !== Number(dependency.version)
        || Number(attachment.evidenceVersion) !== Number(dependency.version)
        || (remote.chat_id && remote.chat_id !== attachment.chatId)
        || (remote.topic_id && remote.topic_id !== attachment.topicId)) {
        throw new HTTPError({ statusCode: 403, statusMessage: 'source_access_revoked' })
      }
      const evidence = await attachmentServiceJson<any>(`/v1/attachments/${encodeURIComponent(id)}/evidence`)
      if (!dependency.content_hash || !evidence.items?.some((item: any) =>
        item.content_hash === dependency.content_hash || item.normalized_content_hash === dependency.content_hash)) {
        throw new HTTPError({ statusCode: 409, statusMessage: 'source_evidence_changed' })
      }
    }
  }
}

export function messageProvenance(parts: unknown): EvidenceProvenance | undefined {
  if (!Array.isArray(parts)) return undefined
  const part = parts.find(item => item?.type === 'data-evidence-provenance')
  const parsed = evidenceProvenanceSchema.safeParse(part?.data)
  return parsed.success ? parsed.data : undefined
}

export function provenancePart(provenance: EvidenceProvenance) {
  return { type: 'data-evidence-provenance', data: provenance }
}

export async function assertDerivedSources(userId: string, proof: unknown): Promise<EvidenceProvenance> {
  const parsed = evidenceProvenanceSchema.safeParse(proof)
  if (!parsed.success || !parsed.data.complete) throw new HTTPError({ statusCode: 409, statusMessage: 'source_provenance_incomplete' })
  await assertSourceDependencies(userId, parsed.data.dependencies)
  return parsed.data
}

export const authoredProvenance = (): EvidenceProvenance => ({ schema_version: 'evidence.provenance.v1', complete: true, dependencies: [] })

export async function readableChatMetadata<T extends { title: string, evidenceProvenance?: unknown }>(userId: string, chat: T): Promise<T> {
  try { await assertDerivedSources(userId, chat.evidenceProvenance); return chat }
  catch { return { ...chat, title: 'Unavailable chat', sourceAccess: 'unavailable' } }
}

/** One live release boundary for a chat list; no grant survives this request. */
export async function readableChatMetadataBatch<T extends { title: string, evidenceProvenance?: unknown }>(userId: string, chats: T[]): Promise<T[]> {
  const proofs = chats.map(chat => evidenceProvenanceSchema.safeParse(chat.evidenceProvenance))
  const dependencies = [...new Map(proofs.flatMap(proof => proof.success && proof.data.complete
    ? proof.data.dependencies : []).map(dependency => [JSON.stringify(dependency), dependency])).values()]
  try {
    await assertSourceDependencies(userId, dependencies)
    return chats.map((chat, index) => proofs[index]?.success && proofs[index].data.complete
      ? chat : { ...chat, title: 'Unavailable chat', sourceAccess: 'unavailable' })
  } catch {
    // Recheck each distinct dependency after a failed batch. One expired
    // attachment must not make every chat repeat its complete source checks.
    const readable = new Set<string>()
    for (let offset = 0; offset < dependencies.length; offset += 8) {
      const batch = dependencies.slice(offset, offset + 8)
      const results = await Promise.allSettled(batch.map(dependency => assertSourceDependencies(userId, [dependency])))
      results.forEach((result, index) => {
        if (result.status === 'fulfilled') readable.add(JSON.stringify(batch[index]))
      })
    }
    return chats.map((chat, index) => {
      const proof = proofs[index]
      return proof?.success && proof.data.complete
        && proof.data.dependencies.every(dependency => readable.has(JSON.stringify(dependency)))
        ? chat : { ...chat, title: 'Unavailable chat', sourceAccess: 'unavailable' }
    })
  }
}

/** Unknown legacy provenance is not made trusted by copying or confirming it. */
export async function assertMessageSources(userId: string, message: { role: string, parts: unknown }): Promise<void> {
  const provenance = messageProvenance(message.parts)
  if (!provenance?.complete) throw new HTTPError({ statusCode: 409, statusMessage: 'source_provenance_incomplete' })
  await assertSourceDependencies(userId, provenance.dependencies)
}

export async function filterReadableMessages<T extends { role: string, parts: unknown }>(userId: string, messages: T[]): Promise<T[]> {
  const checked = await readableChatMetadataBatch(userId, messages.map(message => ({
    title: '', evidenceProvenance: messageProvenance(message.parts)
  })))
  return messages.map((message, index) => checked[index]?.title === '' ? message : { ...message,
    parts: [{ type: 'text', text: 'This message is hidden because its source access or evidence version could not be verified.' },
      { type: 'data-source-access', data: { status: 'unavailable' } }], } as T)
}

export function sourceDependenciesFromCitations(citations: any[]): SourceDependency[] {
  return citations.map(citation => sourceDependencySchema.parse({
    source_type: citation.source_type || 'knowledge', doc_id: citation.doc_id,
    ...Object.fromEntries(['attachment_id', 'knowledge_base_id', 'document_id', 'version_id', 'version', 'content_hash']
      .filter(key => citation[key] != null).map(key => [key, citation[key]])),
  }))
}

export function citationsCovered(provenance: EvidenceProvenance, citations: any[]): boolean {
  return citations.every(citation => provenance.dependencies.some(dependency =>
    dependency.source_type === (citation.source_type || 'knowledge') && dependency.doc_id === citation.doc_id
    && (!citation.version_id || dependency.version_id === citation.version_id)
    && (citation.source_version == null && citation.version == null || String(dependency.version) === String(citation.source_version ?? citation.version))
    && (!citation.knowledge_base_id || dependency.knowledge_base_id === citation.knowledge_base_id)
    && (!citation.content_hash || dependency.content_hash === citation.content_hash)))
}
