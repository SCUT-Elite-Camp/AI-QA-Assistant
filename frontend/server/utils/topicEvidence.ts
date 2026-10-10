import { HTTPError } from 'nitro'
import { accessBackend, assertDerivedSources, assertMessageSources, authoredProvenance, messageProvenance, type EvidenceProvenance } from './sourceAccess'

/** No disk/cache fallback may restore text whose transitive lineage is unknown. */
export async function readableTopic<T extends { title: string, soulContent: string, description?: unknown, tags?: unknown, evidenceProvenance?: unknown }>(userId: string, topic: T): Promise<T> {
  try { await assertDerivedSources(userId, topic.evidenceProvenance); return topic }
  catch { return { ...topic, title: '话题项目', soulContent: '', description: '', tags: [], sourceAccess: 'unavailable' } }
}

export async function discussionEvidence(userId: string, messages: Array<{ role: string, parts: unknown }>): Promise<{ text: string, proof: EvidenceProvenance }> {
  const dependencies = new Map<string, EvidenceProvenance['dependencies'][number]>()
  const lines: string[] = []
  for (const message of messages) {
    await assertMessageSources(userId, message)
    const proof = messageProvenance(message.parts)!
    for (const dep of proof.dependencies) dependencies.set(JSON.stringify(dep), dep)
    const text = Array.isArray(message.parts) ? message.parts.filter(part => part?.type === 'text').map(part => part.text || '').join('') : ''
    if (text.trim()) lines.push(`${message.role}: ${text}`)
  }
  if (!lines.length) throw new HTTPError({ statusCode: 409, statusMessage: 'verified_discussion_required' })
  return { text: lines.join('\n'), proof: { ...authoredProvenance(), dependencies: [...dependencies.values()] } }
}

/** Pool rows are selectors/counts only. Return current authorized projections,
 * never a stale cached title, snippet or physical file from another source. */
export async function readableTopicDocuments(userId: string, documents: any[]): Promise<any[]> {
  const readable: any[] = []
  for (const item of documents) {
    try {
      const response = await accessBackend(userId, `documents/${encodeURIComponent(item.docId)}/source`)
      const source = await response.json() as any
      readable.push({ id: item.id, topicId: item.topicId, docId: item.docId,
        recallCount: item.recallCount, lastRecalledAt: item.lastRecalledAt,
        isRemoved: false, isUserUploaded: item.isUserUploaded || false,
        title: source.title, snippet: String(source.content || '').slice(0, 500),
        sourceUrl: source.source_url, sourceVersion: source.source_version, contentHash: source.content_hash,
      })
    } catch (error) { if ((error as any).statusCode === 503) throw error }
  }
  return readable
}
