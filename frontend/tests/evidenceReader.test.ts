import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ message: vi.fn(), owner: vi.fn(), sources: vi.fn(), backend: vi.fn(), private: vi.fn() }))
vi.mock('nitro', async importOriginal => ({ ...await importOriginal<object>(), defineHandler: (handler: unknown) => handler }))
vi.mock('nitro/h3', async importOriginal => ({ ...await importOriginal<object>(),
  getRouterParam: (_event: unknown, name: string) => name === 'id' ? 'message' : 'evidence' }))
vi.mock('../server/utils/drizzle', async importOriginal => ({
  ...await importOriginal<object>(),
  useDrizzle: () => ({ query: { messages: { findFirst: mocks.message } } }),
  tables: { messages: { id: 'id' } }, eq: vi.fn(),
}))
vi.mock('../server/utils/chatAccess', () => ({ requireOwnedChat: mocks.owner }))
vi.mock('../server/utils/sourceAccess', () => ({ accessBackend: mocks.backend, assertMessageSources: mocks.sources }))
vi.mock('../server/utils/attachmentService', () => ({ attachmentServiceJson: mocks.private }))

import reader from '../server/routes/api/messages/[id]/evidence/[evidence_ref].get'

describe('saved citation reader', () => {
  const excerpt = "Reader resolves a saved message's evidence_ref, then checks current permission, body version, hash, and excerpt."
  const source = "Reader resolves a saved message's evidence\\_ref, then checks current permission, body version, hash, and excerpt."
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.message.mockResolvedValue({ chatId: 'chat', parts: [{ type: 'tool-rag_search', output: [{
      evidence_ref: 'evidence', doc_id: 'doc', source_type: 'knowledge', content_hash: 'body-hash', source_version: 2, snippet: excerpt,
    }] }] })
    mocks.owner.mockResolvedValue({ actor: { userId: 'alice' } })
    mocks.sources.mockResolvedValue(undefined)
    mocks.backend.mockImplementation(async () => Response.json({ content: source }))
  })
  const read = () => (reader as any)({}) as Promise<Response>
  it('returns a version-bound image URL only after saved-message source checks', async () => {
    mocks.message.mockResolvedValue({ chatId: 'chat', parts: [{ type: 'tool-rag_search', output: [{
      evidence_ref: 'evidence', doc_id: 'att_image', attachment_id: 'att_image', source_type: 'attachment',
      content_kind: 'file', content_hash: 'image-hash', source_version: 2, snippet: 'Original image: image.png',
    }] }] })
    mocks.private.mockResolvedValue({ sha256: 'image-hash', evidence_version: 2 })
    const result = await (await read()).json()
    expect(result.source.image_url).toBe('/api/attachments/att_image/content?expected_hash=image-hash&expected_version=2')
    expect(mocks.sources).toHaveBeenCalledTimes(2)
    mocks.private.mockResolvedValue({ sha256: 'edited', evidence_version: 2 })
    await expect(read()).rejects.toMatchObject({ status: 409 })
  })
  it('locates rendered parser text after verifying current body hash and version', async () => {
    const response = await read()
    expect(response.status).toBe(200)
    expect(mocks.backend).toHaveBeenCalledWith('alice', 'documents/doc/source?expected_hash=body-hash&expected_version=2')
    expect(mocks.sources).toHaveBeenCalledTimes(2)
    expect((await response.json()).source.content).toBe(source)
    expect(response.headers.get('Cache-Control')).toContain('no-store')
  })
  it('rejects changed substantive tokens rather than accepting a formatting match', async () => {
    mocks.backend.mockResolvedValue(Response.json({ content: source.replace('body version', 'title') }))
    await expect(read()).rejects.toMatchObject({ status: 409 })
  })
  it('accepts inline code delimiters around otherwise identical text', async () => {
    mocks.backend.mockResolvedValue(Response.json({ content: excerpt.replace('evidence_ref', '`evidence_ref`') }))
    expect((await read()).status).toBe(200)
    expect(mocks.sources).toHaveBeenCalledTimes(2)
  })
  it('preserves version errors and rechecks revocation before releasing source text', async () => {
    mocks.backend.mockRejectedValueOnce(new Error('version_conflict'))
    await expect(read()).rejects.toThrow('version_conflict')
    mocks.sources.mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error('revoked'))
    await expect(read()).rejects.toThrow('revoked')
  })
  it('does not fetch source text when the owned message lineage is no longer authorized', async () => {
    mocks.sources.mockRejectedValueOnce(new Error('source_not_found'))
    await expect(read()).rejects.toThrow('source_not_found')
    expect(mocks.backend).not.toHaveBeenCalled()
  })
  it('reads a noncontiguous table slice only when the current source contains that exact chunk', async () => {
    const slice = '| Test ID | Duration |\n| --- | --- |\n| AR-005 | 14 |'
    mocks.message.mockResolvedValue({ chatId: 'chat', parts: [{ type: 'tool-rag_search', output: [{
      evidence_ref: 'evidence', doc_id: 'doc', source_type: 'knowledge', content_hash: 'body-hash',
      source_version: 2, snippet: slice, locator: { chunk_id: 'doc_chunk_5' },
    }] }] })
    const body = { content: 'Full table with intermediate rows', chunks: [{ chunk_id: 'doc_chunk_5', text: slice }] }
    mocks.backend.mockImplementation(async () => Response.json(body))
    expect((await read()).status).toBe(200)
    expect(mocks.sources).toHaveBeenCalledTimes(2)
    expect(mocks.backend).toHaveBeenCalledWith('alice', 'documents/doc/source?expected_hash=body-hash&expected_version=2')
    mocks.backend.mockImplementation(async () => Response.json({ ...body, chunks: [{ chunk_id: 'doc_chunk_5', text: slice.replace('14', '12') }] }))
    await expect(read()).rejects.toMatchObject({ status: 409 })
  })
})
