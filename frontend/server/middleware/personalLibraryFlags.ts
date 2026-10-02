import { defineHandler, HTTPError } from 'nitro'
import { isPersonalLibraryRouteEnabled } from '../utils/personalLibraryFlags'

export default defineHandler((event) => {
  const path = new URL(event.req.url).pathname

  // The status endpoint remains visible so the UI can discover that the
  // feature is disabled without probing a private service.
  if (path === '/api/attachments/status') return

  const route = path.startsWith('/api/library/') || path === '/api/library'
    ? 'library'
    : path.startsWith('/api/attachments/') || path === '/api/attachments'
      || path.startsWith('/api/attachment-batches/') || path === '/api/attachment-batches'
      ? 'attachments'
      : null

  if (route && !isPersonalLibraryRouteEnabled(route)) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Feature not enabled' })
  }
})
