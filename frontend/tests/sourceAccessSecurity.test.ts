import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import type { HTTPEvent } from 'nitro/h3'
const mocks = vi.hoisted(() => ({ userId: 'alice', agent: vi.fn(), private: vi.fn() }))
vi.mock('../server/utils/session', () => ({ useUserSession: async () => ({ data: { user: { id: mocks.userId } } }) }))
vi.mock('../server/utils/agent-client', () => ({ agentFetch: mocks.agent }))
vi.mock('../server/utils/attachmentService', () => ({ attachmentServiceJson: mocks.private }))
import { tables, useDrizzle } from '../server/utils/drizzle'
import { assertDerivedSources, assertMessageSources, assertSourceDependencies, authoredProvenance,
  citationsCovered, filterReadableMessages, readableChatMetadata, readableChatMetadataBatch, requireEnabledActor, type SourceDependency } from '../server/utils/sourceAccess'
import { appendMessage } from '../server/utils/messageLifecycle'
import { requireOwnedChat } from '../server/utils/chatAccess'
import { evidenceProvenanceSchema } from '../server/utils/evidenceContract'

const enterprise: SourceDependency = { source_type: 'knowledge', doc_id: 'confluence-a', version: 1, content_hash: 'body-hash' }
const personal: SourceDependency = { source_type: 'personal', doc_id: 'personal-a', document_id: 'personal-a',
  knowledge_base_id: 'kb-alice', version_id: 'ver-a', content_hash: 'file-hash' }
const privateProjection = { owner_id: 'alice', knowledge_base_id: 'kb-alice', document_id: 'personal-a',
  version_id: 'ver-a', scope: 'library', source_scope: 'personal', active: true, status: 'ready', sha256: 'file-hash' }

beforeAll(async () => {
  const db = useDrizzle()
  for (const id of ['alice', 'bob', 'disabled']) await db.insert(tables.users).values({ id, providerId: id, provider: 'github',
    email: id + '@test.invalid', name: id, username: id, avatar: '', disabled: id === 'disabled' })
  await db.insert(tables.knowledgeBases).values({ id: 'kb-alice', ownerUserId: 'alice', scopeType: 'personal' })
  await db.insert(tables.libraryDocuments).values({ id: 'personal-a', knowledgeBaseId: 'kb-alice', ownerUserId: 'alice',
    sourceScope: 'personal', filename: 'policy.txt', displayName: 'policy.txt', mimeType: 'text/plain', docType: 'txt', activeVersionId: 'ver-a' })
  await db.insert(tables.documentVersions).values({ id: 'ver-a', documentId: 'personal-a', contentHash: 'file-hash',
    storageRef: 'storage-a', fileSize: 50, versionNumber: 1, status: 'READY' })
  await db.insert(tables.chats).values({ id: 'image-chat', title: 'Image', userId: 'alice' })
  await db.insert(tables.attachmentBatches).values({ id: 'image-batch', ownerId: 'alice', scope: 'chat', chatId: 'image-chat' })
  await db.insert(tables.attachments).values({ id: 'att_image', batchId: 'image-batch', ownerId: 'alice', scope: 'chat',
    chatId: 'image-chat', filename: 'image.png', mimeType: 'image/png', sizeBytes: 100, sha256: 'original-hash', status: 'ready', evidenceVersion: 2 })
})
beforeEach(() => {
  mocks.userId = 'alice'
  mocks.agent.mockReset()
  mocks.private.mockReset()
  mocks.private.mockResolvedValue(privateProjection)
  mocks.agent.mockImplementation(async (path: string) => new Response(JSON.stringify(path.includes('/check')
    ? { allowed_doc_ids: ['confluence-a'], denied_doc_ids: [] } : {}), { status: 200 }))
})

describe('actual BFF guard with migrated SQLite and controlled upstream transports', () => {
  const image = { source_type: 'attachment' as const, doc_id: 'att_image', content_kind: 'file' as const,
    content_hash: 'original-hash', version: 2 }
  const remoteImage = { owner_id: 'alice', scope: 'chat', chat_id: 'image-chat', status: 'ready', evidence_version: 2, sha256: 'original-hash' }
  it('requires a current original-file hash and preserves file lineage', async () => {
    mocks.private.mockResolvedValue(remoteImage)
    await assertSourceDependencies('alice', [image])
    expect(mocks.private).toHaveBeenCalledTimes(1)
    await expect(assertSourceDependencies('bob', [image])).rejects.toMatchObject({ status: 403 })
    expect(citationsCovered({ ...authoredProvenance(), dependencies: [image] }, [image])).toBe(true)
    expect(citationsCovered({ ...authoredProvenance(), dependencies: [image] }, [{ ...image, content_kind: 'excerpt' }])).toBe(false)
  })
  it('rejects image bytes changing without silently accepting the old answer', async () => {
    mocks.private.mockResolvedValue({ ...remoteImage, sha256: 'changed' })
    await expect(assertSourceDependencies('alice', [image])).rejects.toMatchObject({ status: 409 })
    mocks.private.mockResolvedValue({ ...remoteImage, evidence_version: 3 })
    await expect(assertSourceDependencies('alice', [image])).rejects.toMatchObject({ status: 403 })
  })
  it('does not accept a file hash as if it proved an OCR excerpt', async () => {
    mocks.private.mockImplementation(async (path: string) => path.endsWith('/evidence') ? { items: [] } : remoteImage)
    await expect(assertSourceDependencies('alice', [{ ...image, content_kind: 'excerpt' }])).rejects.toMatchObject({ status: 409 })
  })
  it('batches one list boundary, quarantines unknown titles and rechecks the next request', async () => {
    const chats = [{ title: 'First', evidenceProvenance: { ...authoredProvenance(), dependencies: [enterprise] } },
      { title: 'Second', evidenceProvenance: { ...authoredProvenance(), dependencies: [enterprise] } },
      { title: 'Unknown' }]
    expect((await readableChatMetadataBatch('alice', chats)).map(chat => chat.title)).toEqual(['First', 'Second', 'Unavailable chat'])
    expect(mocks.agent).toHaveBeenCalledTimes(2)
    mocks.agent.mockResolvedValue(new Response('{}', { status: 403 }))
    expect((await readableChatMetadataBatch('alice', chats)).every(chat => chat.title === 'Unavailable chat')).toBe(true)
  })
  it('checks shared dependencies once on fallback while keeping unrelated authored chats readable', async () => {
    const chats = [{ title: 'First', evidenceProvenance: { ...authoredProvenance(), dependencies: [enterprise] } },
      { title: 'Second', evidenceProvenance: { ...authoredProvenance(), dependencies: [enterprise] } },
      { title: 'Authored', evidenceProvenance: authoredProvenance() }]
    mocks.agent.mockResolvedValue(new Response('{}', { status: 403 }))
    expect((await readableChatMetadataBatch('alice', chats)).map(chat => chat.title))
      .toEqual(['Unavailable chat', 'Unavailable chat', 'Authored'])
    expect(mocks.agent).toHaveBeenCalledTimes(2)
  })
  it('accepts Pydantic nulls without treating missing source-specific proof as valid', async () => {
    const proof = evidenceProvenanceSchema.parse({ ...authoredProvenance(), trace_id: 'python-wire', dependencies: [{
      ...enterprise, knowledge_base_id: null, document_id: null, version_id: null,
    }] })
    expect(proof.dependencies[0]!.version_id).toBeUndefined()
    await assertSourceDependencies('alice', proof.dependencies)
    const missing = evidenceProvenanceSchema.parse({ ...proof, dependencies: [{ source_type: 'personal', doc_id: 'personal-a',
      knowledge_base_id: null, document_id: null, version_id: null, version: null, content_hash: null }] })
    await expect(assertSourceDependencies('alice', missing.dependencies)).rejects.toMatchObject({ status: 409 })
  })
  it('requires a current enabled local actor', async () => {
    expect(await requireEnabledActor({} as HTTPEvent)).toBe('alice')
    mocks.userId = 'missing'
    await expect(requireEnabledActor({} as HTTPEvent)).rejects.toMatchObject({ status: 401 })
    mocks.userId = 'disabled'
    await expect(requireEnabledActor({} as HTTPEvent)).rejects.toMatchObject({ status: 403 })
  })
  it('does not convert Topic viewer access or historical ownership into write permission', async () => {
    const db = useDrizzle()
    await db.insert(tables.topics).values({ id: 'topic-readonly', mainChatId: 'chat-readonly', title: 'test' })
    await db.insert(tables.chats).values({ id: 'chat-readonly', userId: 'alice', topicId: 'topic-readonly', title: 'test' })
    await db.insert(tables.topicMembers).values({ topicId: 'topic-readonly', userId: 'bob', role: 'viewer' })
    mocks.userId = 'bob'
    await expect(requireOwnedChat({} as HTTPEvent, 'chat-readonly')).resolves.toBeDefined()
    await expect(requireOwnedChat({} as HTTPEvent, 'chat-readonly', 'editor')).rejects.toMatchObject({ status: 403 })
    mocks.userId = 'alice'
    await expect(requireOwnedChat({} as HTTPEvent, 'chat-readonly')).rejects.toMatchObject({ status: 403 })
  })
  it('checks both native permission and the expected body version on every read', async () => {
    await assertSourceDependencies('alice', [enterprise])
    await assertSourceDependencies('alice', [enterprise])
    expect(mocks.agent).toHaveBeenCalledTimes(4)
    const call = mocks.agent.mock.calls[1]!
    expect(call[0]).toContain('expected_hash=body-hash&expected_version=1')
    expect(call[1]).toMatchObject({ redirect: 'error', headers: { 'X-User-ID': 'alice' } })
  })
  it('never trusts an old positive ACL when the current read denies', async () => {
    await assertSourceDependencies('alice', [enterprise])
    mocks.agent.mockResolvedValue(new Response(JSON.stringify({ allowed_doc_ids: [], denied_doc_ids: ['confluence-a'] })))
    await expect(assertSourceDependencies('alice', [enterprise])).rejects.toMatchObject({ status: 403 })
  })
  it.each([403, 409, 503])('retains source failure status %s rather than serving stale bodies', async status => {
    mocks.agent.mockImplementation(async (path: string) => new Response('{}', { status: path.includes('/check') ? 200 : status }))
    mocks.agent.mockResolvedValueOnce(new Response(JSON.stringify({ allowed_doc_ids: ['confluence-a'], denied_doc_ids: [] })))
    await expect(assertSourceDependencies('alice', [enterprise])).rejects.toMatchObject({ status })
  })
  it('quarantines unknown legacy message and title provenance', async () => {
    const old = { role: 'assistant', parts: [{ type: 'text', text: 'secret legacy answer' }] }
    await expect(assertMessageSources('alice', old)).rejects.toMatchObject({ status: 409 })
    const hidden = await filterReadableMessages('alice', [old])
    expect(JSON.stringify(hidden)).not.toContain('secret legacy answer')
    expect((await readableChatMetadata('alice', { title: 'secret old title' })).title).toBe('Unavailable chat')
    expect(mocks.agent).not.toHaveBeenCalled()
  })
  it('requires complete provenance even with an empty dependency array', async () => {
    await expect(assertDerivedSources('alice', { ...authoredProvenance(), complete: false })).rejects.toMatchObject({ status: 409 })
    await expect(assertDerivedSources('alice', authoredProvenance())).resolves.toMatchObject({ complete: true })
  })
  it('checks the actual personal owner, active version and remote object', async () => {
    await assertSourceDependencies('alice', [personal])
    await expect(assertSourceDependencies('bob', [personal])).rejects.toMatchObject({ status: 403 })
    await expect(assertSourceDependencies('alice', [{ ...personal, version_id: 'ver-old' }])).rejects.toMatchObject({ status: 403 })
    expect(mocks.private).toHaveBeenCalledTimes(1)
  })
  it.each(['owner_id', 'version_id', 'source_scope', 'sha256'])('rejects mismatched personal remote %s', async field => {
    mocks.private.mockResolvedValue({ ...privateProjection, [field]: 'different' })
    await expect(assertSourceDependencies('alice', [personal])).rejects.toMatchObject({ status: 403 })
  })
  it('rejects personal evidence with missing hash before remote IO', async () => {
    await expect(assertSourceDependencies('alice', [{ ...personal, content_hash: undefined }])).rejects.toMatchObject({ status: 409 })
    expect(mocks.private).not.toHaveBeenCalled()
  })
  it('does not let citations change their bound source version or namespace', () => {
    const proof = { ...authoredProvenance(), dependencies: [enterprise] }
    expect(citationsCovered(proof, [{ doc_id: 'confluence-a', source_version: 2 }])).toBe(false)
    expect(citationsCovered(proof, [{ doc_id: 'confluence-a', source_type: 'personal' }])).toBe(false)
    expect(citationsCovered(proof, [{ doc_id: 'confluence-a', source_version: '1', content_hash: 'body-hash' }])).toBe(true)
  })
})
