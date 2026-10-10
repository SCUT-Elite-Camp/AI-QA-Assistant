import { defineHandler } from 'nitro'
import { requireCsrf } from '../utils/attachmentAuth'
import { requireAdministrator, requireEnabledActor } from '../utils/sourceAccess'

export default defineHandler(async (event) => {
  const path = new URL(event.req.url).pathname
  if (!path.startsWith('/api/') || /^\/api\/(?:auth|session)(?:\/|$)/.test(path)
    || path === '/api/attachments/status') return
  await requireEnabledActor(event)
  if (!['GET', 'HEAD', 'OPTIONS'].includes(event.req.method)) requireCsrf(event)
  if (path === '/api/metrics' || /^\/api\/documents\/(?:upload|delete|reindex)$/.test(path)) {
    await requireAdministrator(event)
  }
})
