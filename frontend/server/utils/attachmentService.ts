import { HTTPError } from 'nitro'

const BASE_URL = (process.env.ATTACHMENT_SERVICE_URL || 'http://127.0.0.1:8200').replace(/\/$/, '')

export async function attachmentServiceFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const secret = process.env.ATTACHMENT_INTERNAL_SECRET || ''
  if (!secret) throw new HTTPError({ statusCode: 503, statusMessage: 'attachments_unavailable' })
  let response: Response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers: { ...Object.fromEntries(new Headers(init.headers).entries()), Authorization: `Bearer ${secret}` },
      signal: init.signal || AbortSignal.timeout(120_000)
    })
  } catch {
    throw new HTTPError({ statusCode: 503, statusMessage: 'attachments_unavailable' })
  }
  return response
}

export async function attachmentServiceJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await attachmentServiceFetch(path, init)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new HTTPError({ statusCode: response.status, statusMessage: (body as any)?.detail?.code || 'attachment_service_error', data: body })
  }
  return body as T
}
