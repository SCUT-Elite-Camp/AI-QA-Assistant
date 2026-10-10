import { defineHandler } from 'nitro'
import { getMetrics } from '../../utils/metrics'
import { accessBackend, requireAdministrator } from '../../utils/sourceAccess'

export default defineHandler(async (event) => {
  const userId = await requireAdministrator(event)
  const payload = await (await accessBackend(userId, 'documents')).json() as any
  const documents = Array.isArray(payload) ? payload : payload.documents || payload.items || []
  return { ...getMetrics(), counts: { documents: documents.length }, indexedDocs: documents,
    services: { agentApi: 'healthy', webServer: 'healthy', database: 'healthy' } }
})
