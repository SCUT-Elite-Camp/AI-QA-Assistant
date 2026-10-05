import { randomUUID } from 'node:crypto'
import { defineHandler, HTTPError } from 'nitro'
import { eq, tables, useDrizzle } from '../../../../utils/drizzle'
import { requireCsrf, requirePrincipal } from '../../../../utils/attachmentAuth'
import { attachmentServiceFetch, attachmentServiceJson } from '../../../../utils/attachmentService'
import { getOrCreateDefaultLibrary, getPersonalLibraryDocument } from '../../../../utils/library'
import {
  activateDesiredVersion,
  createDocumentWithInitialVersion,
  createLibraryVersion,
  findVersionByHash,
  getActiveVersion,
  resolveUploadedHash,
  setDesiredVersion,
} from '../../../../utils/libraryVersionService'

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
  const existingDocument = requestedDocumentId
    ? await getPersonalLibraryDocument(userId, library.id, requestedDocumentId, db)
    : undefined
  if (requestedDocumentId && !existingDocument) {
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
    const activeVersion = existingDocument ? await getActiveVersion(existingDocument) : undefined
    const duplicate = existingDocument ? await findVersionByHash(documentId, remote.sha256) : undefined
    const hashResolution = resolveUploadedHash(activeVersion?.contentHash, remote.sha256, duplicate?.status)
    if (hashResolution === 'unchanged' && activeVersion) {
      await attachmentServiceFetch(`/v1/attachments/${versionId}`, { method: 'DELETE' })
      remoteCreated = false
      return { document_id: documentId, version_id: activeVersion.id, version_number: activeVersion.versionNumber, status: activeVersion.status, unchanged: true }
    }
    if (duplicate && existingDocument && hashResolution !== 'create') {
      await attachmentServiceFetch(`/v1/attachments/${versionId}`, { method: 'DELETE' })
      remoteCreated = false
      await setDesiredVersion(documentId, duplicate.id)
      if (hashResolution === 'reactivate') {
        await activateDesiredVersion(
          { ...existingDocument, desiredVersionId: duplicate.id },
          duplicate,
        )
        return { document_id: documentId, version_id: duplicate.id, version_number: duplicate.versionNumber, status: duplicate.status, unchanged: false, reactivated: true }
      }
      if (hashResolution === 'retry') {
        await attachmentServiceJson(`/v1/attachments/${duplicate.storageRef}/retry`, { method: 'POST' })
        await db.update(tables.documentVersions).set({ status: 'REINDEXING', errorCode: '', errorMessage: '', updatedAt: new Date() })
          .where(eq(tables.documentVersions.id, duplicate.id))
        return { document_id: documentId, version_id: duplicate.id, version_number: duplicate.versionNumber, status: 'REINDEXING', unchanged: false, retrying: true }
      }
      return { document_id: documentId, version_id: duplicate.id, version_number: duplicate.versionNumber, status: duplicate.status, unchanged: false, pending: true }
    }
    const extension = filename.includes('.') ? filename.split('.').pop()!.toLowerCase() : ''
    let versionNumber: number
    const version = {
      id: versionId, documentId, contentHash: remote.sha256,
      storageRef: versionId, fileSize: remote.size_bytes,
      status: remote.status === 'parsing' ? 'PARSING' as const : 'UPLOADED' as const,
      createdAt: new Date(), updatedAt: new Date()
    }
    try {
      if (existingDocument) {
        versionNumber = await createLibraryVersion(documentId, version, {
          filename, displayName: filename, mimeType, docType: extension,
        }, db)
      } else {
        versionNumber = await createDocumentWithInitialVersion({
          id: documentId, knowledgeBaseId: library.id, ownerUserId: userId,
          sourceScope: 'personal', sourceType: 'upload', filename,
          displayName: filename, mimeType, docType: extension,
          createdAt: new Date(), updatedAt: new Date(),
        }, version, db)
      }
    } catch (error) {
      // A concurrent identical upload may win the unique hash constraint.
      const winner = await findVersionByHash(documentId, remote.sha256)
      if (!winner) throw error
      await attachmentServiceFetch(`/v1/attachments/${versionId}`, { method: 'DELETE' })
      remoteCreated = false
      return { document_id: documentId, version_id: winner.id, version_number: winner.versionNumber, status: winner.status, unchanged: true, concurrent: true }
    }
    return { document_id: documentId, version_id: versionId, version_number: versionNumber, status: remote.status, unchanged: false }
  } catch (error) {
    if (remoteCreated) await attachmentServiceFetch(`/v1/attachments/${versionId}`, { method: 'DELETE' }).catch(() => undefined)
    throw error
  }
})
