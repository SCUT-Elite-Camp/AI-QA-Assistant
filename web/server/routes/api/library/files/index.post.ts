import { randomUUID } from 'node:crypto'
import { defineHandler, HTTPError } from 'nitro'
import { and, eq, tables, useDrizzle } from '../../../../utils/drizzle'
import { requireCsrf, requirePrincipal } from '../../../../utils/attachmentAuth'
import { attachmentServiceFetch, attachmentServiceJson } from '../../../../utils/attachmentService'
import { getOrCreateDefaultLibrary } from '../../../../utils/library'

export default defineHandler(async (event) => {
  requireCsrf(event)
  const userId = await requirePrincipal(event)
  const filenameHeader = event.req.headers.get('x-file-name-b64')?.trim() || ''
  let filename = ''
  try { filename = Buffer.from(filenameHeader, 'base64url').toString('utf8').trim() } catch {}
  const sizeBytes = Number(event.req.headers.get('content-length') || 0)
  const mimeType = event.req.headers.get('content-type')?.split(';', 1)[0] || 'application/octet-stream'
  if (!filename || filename.includes('\0') || Buffer.byteLength(filename, 'utf8') > 255 || !Number.isSafeInteger(sizeBytes) || sizeBytes <= 0 || sizeBytes > 50 * 1024 * 1024) {
    throw new HTTPError({ statusCode: 422, statusMessage: 'invalid_upload_headers' })
  }
  const db = useDrizzle()
  const library = await getOrCreateDefaultLibrary(userId)
  const requestedDocumentId = event.req.headers.get('x-document-id')?.trim() || ''
  let existingDocument = requestedDocumentId
    ? await db.query.libraryDocuments.findFirst({ where: and(eq(tables.libraryDocuments.id, requestedDocumentId), eq(tables.libraryDocuments.ownerUserId, userId), eq(tables.libraryDocuments.knowledgeBaseId, library.id)) })
    : undefined
  if (requestedDocumentId && (!existingDocument || existingDocument.deletedAt)) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'library_document_not_found' })
  }
  const documentId = existingDocument?.id || `doc_${randomUUID().replace(/-/g, '')}`
  const versionId = `ver_${randomUUID().replace(/-/g, '')}`
  let remoteCreated = false
  try {
    const remote = await attachmentServiceJson<any>(`/v1/attachments/${versionId}`, {
      method: 'POST',
      headers: {
        'Content-Type': mimeType,
        'Content-Length': String(sizeBytes),
        'X-Filename-B64': filenameHeader,
        'X-Owner-ID': userId,
        'X-Dedupe-Domain': `user:${userId}`,
        'X-Scope': 'library',
        'X-Knowledge-Base-ID': library.id,
        'X-Document-ID': documentId,
        'X-Version-ID': versionId,
        'X-Source-Scope': 'personal'
      },
      body: event.req.body,
      duplex: 'half'
    } as RequestInit & { duplex: 'half' })
    remoteCreated = true
    const duplicate = existingDocument
      ? await db.query.documentVersions.findFirst({ where: and(eq(tables.documentVersions.documentId, documentId), eq(tables.documentVersions.contentHash, remote.sha256)) })
      : undefined
    if (duplicate) {
      await attachmentServiceFetch(`/v1/attachments/${versionId}`, { method: 'DELETE' })
      remoteCreated = false
      return { document_id: documentId, version_id: duplicate.id, status: duplicate.status, unchanged: true }
    }
    const extension = filename.includes('.') ? filename.split('.').pop()!.toLowerCase() : ''
    await db.transaction(async tx => {
      if (!existingDocument) {
        await tx.insert(tables.libraryDocuments).values({
          id: documentId, knowledgeBaseId: library.id, ownerUserId: userId,
          sourceScope: 'personal', sourceType: 'upload', filename,
          displayName: filename, mimeType, docType: extension,
          createdAt: new Date(), updatedAt: new Date()
        })
      } else {
        await tx.update(tables.libraryDocuments).set({
          filename, displayName: filename, mimeType, docType: extension, updatedAt: new Date()
        }).where(eq(tables.libraryDocuments.id, documentId))
      }
      await tx.insert(tables.documentVersions).values({
        id: versionId, documentId, contentHash: remote.sha256,
        storageRef: versionId, fileSize: remote.size_bytes,
        status: remote.status === 'parsing' ? 'PARSING' : 'UPLOADED',
        createdAt: new Date(), updatedAt: new Date()
      })
    })
    return { document_id: documentId, version_id: versionId, status: remote.status, unchanged: false }
  } catch (error) {
    if (remoteCreated) await attachmentServiceFetch(`/v1/attachments/${versionId}`, { method: 'DELETE' }).catch(() => undefined)
    throw error
  }
})
