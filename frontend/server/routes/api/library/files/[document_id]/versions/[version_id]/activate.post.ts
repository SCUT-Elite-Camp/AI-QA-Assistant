import { defineHandler, HTTPError } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { and, eq, tables, useDrizzle } from '../../../../../../../utils/drizzle'
import { requireCsrf } from '../../../../../../../utils/attachmentAuth'
import { requireLibraryDocument } from '../../../../../../../utils/library'
import { activateDesiredVersion, setDesiredVersion } from '../../../../../../../utils/libraryVersionService'

export default defineHandler(async (event) => {
  requireCsrf(event)
  const documentId = getRouterParam(event, 'document_id') || ''
  const versionId = getRouterParam(event, 'version_id') || ''
  const { document } = await requireLibraryDocument(event, documentId)
  const version = await useDrizzle().query.documentVersions.findFirst({
    where: and(
      eq(tables.documentVersions.id, versionId),
      eq(tables.documentVersions.documentId, document.id),
    ),
  })
  if (!version) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'library_version_not_found' })
  }
  if (version.status !== 'READY') {
    throw new HTTPError({ statusCode: 409, statusMessage: 'library_version_not_ready' })
  }
  await setDesiredVersion(document.id, version.id)
  const activated = await activateDesiredVersion(
    { ...document, desiredVersionId: version.id },
    version,
  )
  if (!activated) {
    throw new HTTPError({ statusCode: 409, statusMessage: 'library_version_activation_conflict' })
  }
  return {
    document_id: document.id,
    version_id: version.id,
    version_number: version.versionNumber,
    active: true,
  }
})
