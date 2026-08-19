import { randomUUID } from 'node:crypto'
import { defineHandler, HTTPError } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { and, eq, sql, tables, useDrizzle } from '../../../../utils/drizzle'
import { requireCsrf, requirePrincipal, requireTopicRole } from '../../../../utils/attachmentAuth'
import { attachmentServiceJson } from '../../../../utils/attachmentService'
import { attachmentBatchExpired, isAnonymousAttachmentPrincipal } from '../../../../../shared/utils/attachmentScope'

const BATCH_MAX_FILES = 10
const BATCH_MAX_BYTES = 100 * 1024 * 1024

export default defineHandler(async (event) => {
  requireCsrf(event)
  const userId = await requirePrincipal(event)
  const batchId = getRouterParam(event, 'batch_id') || ''
  const filenameHeader = event.req.headers.get('x-file-name-b64')?.trim() || ''
  let filename = ''
  try {
    filename = Buffer.from(filenameHeader, 'base64url').toString('utf8').trim()
  } catch {}
  const mimeType = event.req.headers.get('content-type')?.split(';', 1)[0] || 'application/octet-stream'
  const sizeBytes = Number(event.req.headers.get('content-length') || 0)
  if (!filename || Buffer.byteLength(filename, 'utf8') > 255 || filename.includes('\0') || !Number.isSafeInteger(sizeBytes) || sizeBytes <= 0 || sizeBytes > 50 * 1024 * 1024) {
    throw new HTTPError({ statusCode: 422, statusMessage: 'invalid_upload_headers' })
  }
  const db = useDrizzle()
  const batch = await db.query.attachmentBatches.findFirst({ where: and(eq(tables.attachmentBatches.id, batchId), eq(tables.attachmentBatches.ownerId, userId)) })
  if (!batch) throw new HTTPError({ statusCode: 404, statusMessage: 'batch_not_found' })
  if (attachmentBatchExpired(batch.expiresAt)) {
    throw new HTTPError({ statusCode: 410, statusMessage: 'batch_expired' })
  }
  if (batch.scope === 'topic' && isAnonymousAttachmentPrincipal(userId)) {
    throw new HTTPError({ statusCode: 403, statusMessage: 'anonymous_topic_attachment_forbidden' })
  }
  if (batch.topicId) await requireTopicRole(event, batch.topicId, 'editor')
  if (batch.fileCount >= BATCH_MAX_FILES || batch.totalBytes + sizeBytes > BATCH_MAX_BYTES) {
    throw new HTTPError({ statusCode: 413, statusMessage: 'batch_limit_exceeded' })
  }
  const attachmentId = `att_${randomUUID().replace(/-/g, '')}`
  const expiresAt = batch.scope === 'topic' ? null : Math.floor(Date.now() / 1000) + 24 * 60 * 60
  const dedupeDomain = batch.topicId ? `topic:${batch.topicId}` : `user:${userId}`
  const filenameB64 = Buffer.from(filename, 'utf8').toString('base64url')
  try {
    const result = await attachmentServiceJson<any>(`/v1/attachments/${attachmentId}`, {
      method: 'POST',
      headers: {
        'Content-Type': mimeType,
        'Content-Length': String(sizeBytes),
        'X-Filename-B64': filenameB64,
        'X-Owner-ID': userId,
        'X-Dedupe-Domain': dedupeDomain,
        'X-Scope': batch.scope,
        ...(expiresAt ? { 'X-Expires-At': String(expiresAt) } : {})
      },
      body: event.req.body,
      // Required by Node fetch for a streamed request body.
      duplex: 'half'
    } as RequestInit & { duplex: 'half' })
    if (result.size_bytes !== sizeBytes) {
      throw new HTTPError({ statusCode: 422, statusMessage: 'upload_length_mismatch' })
    }
    await db.transaction(async tx => {
      const current = await tx.query.attachmentBatches.findFirst({ where: eq(tables.attachmentBatches.id, batch.id) })
      if (!current || current.fileCount >= BATCH_MAX_FILES || current.totalBytes + sizeBytes > BATCH_MAX_BYTES) {
        throw new HTTPError({ statusCode: 409, statusMessage: 'batch_limit_race' })
      }
      await tx.insert(tables.attachments).values({
        id: attachmentId, batchId: batch.id, ownerId: userId, scope: batch.scope,
        chatId: batch.chatId, topicId: batch.topicId, filename: result.filename,
        mimeType: result.mime_type, sizeBytes: result.size_bytes, sha256: result.sha256,
        status: result.status, visionStatus: result.vision_status || 'not_requested',
        evidenceVersion: result.evidence_version || 1,
        expiresAt: expiresAt ? new Date(expiresAt * 1000) : null,
      })
      await tx.update(tables.attachmentBatches).set({ fileCount: sql`${tables.attachmentBatches.fileCount} + 1`, totalBytes: sql`${tables.attachmentBatches.totalBytes} + ${sizeBytes}` }).where(eq(tables.attachmentBatches.id, batch.id))
    })
    return result
  } catch (error) {
    await fetch(`${process.env.ATTACHMENT_SERVICE_URL || 'http://127.0.0.1:8200'}/v1/attachments/${attachmentId}`, { method: 'DELETE', headers: { Authorization: `Bearer ${process.env.ATTACHMENT_INTERNAL_SECRET || ''}` } }).catch(() => undefined)
    throw error
  }
})
