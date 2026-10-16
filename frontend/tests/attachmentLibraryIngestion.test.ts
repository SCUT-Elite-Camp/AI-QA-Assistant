import { beforeEach, describe, expect, it, vi } from 'vitest'

const remote = vi.hoisted(() => ({ json: vi.fn(), fetch: vi.fn() }))
vi.mock('nitro', async original => ({ ...await original<object>(), defineHandler: (handler: unknown) => handler }))
vi.mock('nitro/h3', async original => ({ ...await original<object>(), getRouterParam: () => 'upload-batch' }))
vi.mock('../server/utils/attachmentAuth', () => ({
  requireCsrf: vi.fn(), requirePrincipal: async () => 'alice', requireTopicRole: vi.fn(),
}))
vi.mock('../server/utils/attachmentService', () => ({ attachmentServiceJson: remote.json, attachmentServiceFetch: remote.fetch }))

import upload from '../server/routes/api/attachment-batches/[batch_id]/files.post'
import { tables, useDrizzle } from '../server/utils/drizzle'
import { syncPendingLibraryVersions } from '../server/utils/library'

beforeEach(async () => {
  vi.clearAllMocks()
  const db = useDrizzle()
  await db.$client.execute('DROP TRIGGER IF EXISTS reject_library_document')
  await db.delete(tables.attachments)
  await db.delete(tables.attachmentBatches)
  await db.delete(tables.documentVersions)
  await db.delete(tables.libraryDocuments)
  await db.delete(tables.knowledgeBases)
  await db.insert(tables.attachmentBatches).values({ id: 'upload-batch', ownerId: 'alice', scope: 'draft' })
  remote.json.mockImplementation(async (_path: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      return { filename: 'notes.txt', mime_type: 'text/plain', size_bytes: 7, sha256: 'source-hash', status: 'parsing' }
    }
    return { status: 'ready', error_code: '' }
  })
  remote.fetch.mockResolvedValue(new Response(null, { status: 204 }))
})

function event() {
  return { req: { headers: new Headers({
    'x-file-name-b64': Buffer.from('notes.txt').toString('base64url'),
    'content-type': 'text/plain', 'content-length': '7',
    'x-owner-id': 'forged-browser-owner', 'x-library-kb-id': 'forged-browser-kb',
  }), body: 'context' } }
}

describe('conversation uploads automatically enter Personal Library', () => {
  it('uses the session owner and creates an inactive desired library version in the attachment transaction', async () => {
    const result = await (upload as any)(event())
    const db = useDrizzle()
    const documents = await db.select().from(tables.libraryDocuments)
    const versions = await db.select().from(tables.documentVersions)
    const attachments = await db.select().from(tables.attachments)
    expect(attachments).toHaveLength(1)
    expect(documents).toHaveLength(1)
    expect(documents[0]).toMatchObject({ ownerUserId: 'alice', sourceScope: 'personal', activeVersionId: null, desiredVersionId: result.version_id })
    expect(versions[0]).toMatchObject({ id: result.version_id, documentId: result.document_id, status: 'PARSING', versionNumber: 1 })
    const headers = remote.json.mock.calls[0][1].headers
    expect(headers['X-Owner-ID']).toBe('alice')
    expect(headers['X-Library-KB-ID']).toBe(documents[0].knowledgeBaseId)
    expect(headers['X-Library-Version-ID']).toBe(result.version_id)
    expect(remote.json).toHaveBeenCalledTimes(1)

    remote.json.mockImplementation(async (path: string) => path.endsWith('/library/activate') ? { activated: true } : { status: 'ready' })
    await syncPendingLibraryVersions()
    const activated = await db.select().from(tables.libraryDocuments)
    expect(activated[0].activeVersionId).toBe(result.version_id)
    expect(remote.json).toHaveBeenCalledWith(`/v1/attachments/${result.version_id}/library/activate`, expect.any(Object))
  })

  it('rolls back both Web records and deletes both remote objects if library persistence fails', async () => {
    const db = useDrizzle()
    await db.$client.execute("CREATE TRIGGER reject_library_document BEFORE INSERT ON library_documents BEGIN SELECT RAISE(ABORT, 'injected_failure'); END")
    await expect((upload as any)(event())).rejects.toThrow()
    expect(await db.select().from(tables.attachments)).toHaveLength(0)
    expect(await db.select().from(tables.libraryDocuments)).toHaveLength(0)
    expect(await db.select().from(tables.documentVersions)).toHaveLength(0)
    expect(remote.fetch.mock.calls.map(call => call[0])).toEqual([
      expect.stringMatching(/^\/v1\/attachments\/att_/), expect.stringMatching(/^\/v1\/attachments\/ver_/),
    ])
    const batches = await db.select().from(tables.attachmentBatches)
    expect(batches[0].fileCount).toBe(0)
  })
})
