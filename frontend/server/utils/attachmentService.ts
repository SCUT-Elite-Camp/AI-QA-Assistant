import { HTTPError } from 'nitro'

const BASE_URL = `${(process.env.AGENT_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')}/private-files`

export async function attachmentServiceFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const secret = process.env.ATTACHMENT_INTERNAL_SECRET || ''
  if (!secret) throw new HTTPError({ statusCode: 503, statusMessage: 'attachments_unavailable' })
  let response: Response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      redirect: 'error',
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
    const code = typeof (body as any)?.detail?.code === 'string' ? (body as any).detail.code : 'attachment_service_error'
    throw new HTTPError({ statusCode: response.status, statusMessage: code, data: { code } })
  }
  return body as T
}
