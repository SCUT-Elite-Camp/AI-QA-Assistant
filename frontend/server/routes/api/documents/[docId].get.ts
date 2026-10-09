import { defineHandler } from 'nitro'
import { getRouterParam, getQuery } from 'nitro/h3'
import { accessBackend, requireEnabledActor } from '../../../utils/sourceAccess'

export default defineHandler(async (event) => {
  const userId = await requireEnabledActor(event)
  const docId = getRouterParam(event, 'docId') || ''
  const query = getQuery(event)
  const params = new URLSearchParams()
  for (const key of ['expected_version', 'expected_hash']) {
    if (typeof query[key] === 'string') params.set(key, query[key])
  }
  const response = await accessBackend(userId, `documents/${encodeURIComponent(docId)}/source?${params}`)
  return new Response(response.body, { status: response.status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'private, no-store' } })
})
