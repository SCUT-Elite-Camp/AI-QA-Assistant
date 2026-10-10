import { HTTPError } from 'nitro'
import { readBody, type HTTPEvent } from 'nitro/h3'
import { agentFetch } from './agent-client'
import { requireActor } from './chatAccess'
import { requireCsrf } from './attachmentAuth'
import { eq, tables, useDrizzle } from './drizzle'
import { requireEnabledActor } from './sourceAccess'

/** Research always uses a signed-in, currently enabled server-session actor. */
export async function requireResearchActor(event: HTTPEvent): Promise<string> {
  return requireEnabledActor(event)
}

/** Decode route parameters without permitting traversal or a second URL. */
function pathSegment(value: string): string {
  let decoded = value
  try {
    for (let count = 0; count < 3 && decoded.includes('%'); count++) decoded = decodeURIComponent(decoded)
  } catch {
    throw new HTTPError({ statusCode: 400, statusMessage: 'Invalid Research path' })
  }
  if (!decoded || decoded === '.' || decoded === '..' || /[/\\%?#\u0000-\u001f\u007f]/u.test(decoded)) {
    throw new HTTPError({ statusCode: 400, statusMessage: 'Invalid Research path' })
  }
  return decoded
}

export function researchBackendPath(path: string, method: string): string {
  const segments = path.split('/').map(pathSegment)
  const resource = segments.join('/')
  const validGet = resource === 'documents'
    || /^jobs\/research-[a-zA-Z0-9]+(?:\/(?:plan|report|progress|events|evaluation-trace))?$/.test(resource)
    || (segments.length === 5 && segments[0] === 'jobs'
      && /^research-[a-zA-Z0-9]+$/.test(segments[1]!)
      && segments[2] === 'documents' && segments[4] === 'source')
  const validPost = resource === 'jobs'
    || /^jobs\/research-[a-zA-Z0-9]+\/(?:approve|cancel|messages|plan\/revisions)$/.test(resource)
  if (!(method === 'GET' && validGet) && !(method === 'POST' && validPost)) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Research endpoint not found' })
  }
  return `/api/research/${segments.map(encodeURIComponent).join('/')}`
}

/** Never pass browser Authorization, identity headers, cookies, or redirects. */
export async function fetchResearchBackend(
  userId: string,
  path: string,
  options: { method?: 'GET' | 'POST', body?: unknown, search?: string } = {},
): Promise<Response> {
  const method = options.method ?? 'GET'
  const backendPath = researchBackendPath(path, method)
  let response: Response
  try {
    response = await agentFetch(`${backendPath}${options.search ?? ''}`, {
      method,
      headers: { 'X-User-ID': userId },
      ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
      redirect: 'error',
    })
  } catch {
    throw new HTTPError({ statusCode: 502, statusMessage: 'Research backend unavailable' })
  }
  const headers = new Headers({ 'Cache-Control': 'private, no-store' })
  for (const name of ['content-type', 'content-disposition', 'retry-after']) {
    const value = response.headers.get(name)
    if (value) headers.set(name, value)
  }
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers })
}

export async function proxyResearchRequest(event: HTTPEvent, path: string): Promise<Response> {
  const userId = await requireResearchActor(event)
  const method = event.req.method
  researchBackendPath(path, method)
  if (method === 'POST') requireCsrf(event)
  return fetchResearchBackend(userId, path, {
    method: method as 'GET' | 'POST',
    search: new URL(event.req.url).search,
    ...(method === 'POST' ? { body: await readBody(event) } : {}),
  })
}
