import { createHash, timingSafeEqual } from 'node:crypto'
import { HTTPError } from 'nitro'
import { getCookie, type HTTPEvent } from 'nitro/h3'
import { and, eq, tables, useDrizzle } from './drizzle'
import { useUserSession } from './session'

export type TopicRole = 'owner' | 'editor' | 'viewer'
const RANK: Record<TopicRole, number> = { viewer: 1, editor: 2, owner: 3 }

export function topicRoleAtLeast(actual: TopicRole, minimum: TopicRole): boolean {
  return RANK[actual] >= RANK[minimum]
}

export function ensureOwnerContinuity(currentRole: TopicRole | undefined, nextRole: TopicRole | undefined, ownerCount: number): void {
  if (currentRole === 'owner' && nextRole !== 'owner' && ownerCount <= 1) {
    throw new HTTPError({ statusCode: 409, statusMessage: 'last_owner_required' })
  }
}

export async function requirePrincipal(event: HTTPEvent): Promise<string> {
  const session = await useUserSession(event)
  const userId = session.data.user?.id
  if (userId) return userId
  const allowAnonymous = process.env.NODE_ENV !== 'production'
    && process.env.ALLOW_ANONYMOUS_UPLOAD === 'true'
  if (allowAnonymous && session.id) return `anonymous:${session.id}`
  throw new HTTPError({ statusCode: 401, statusMessage: 'login_required' })
}

export function requireCsrf(event: HTTPEvent): void {
  const cookie = getCookie(event, 'csrf-token')
  const header = event.req.headers.get('x-csrf-token')
  if (!cookie || !header) throw new HTTPError({ statusCode: 403, statusMessage: 'csrf_failed' })
  const left = Buffer.from(cookie)
  const right = Buffer.from(header)
  if (left.length !== right.length || !timingSafeEqual(left, right)) {
    throw new HTTPError({ statusCode: 403, statusMessage: 'csrf_failed' })
  }
}

export async function requireTopicRole(event: HTTPEvent, topicId: string, minimum: TopicRole = 'viewer'): Promise<{ userId: string, role: TopicRole }> {
  const userId = await requirePrincipal(event)
  const db = useDrizzle()
  const member = await db.query.topicMembers.findFirst({
    where: and(eq(tables.topicMembers.topicId, topicId), eq(tables.topicMembers.userId, userId))
  })
  if (!member || !topicRoleAtLeast(member.role, minimum)) {
    throw new HTTPError({ statusCode: 403, statusMessage: 'topic_forbidden' })
  }
  return { userId, role: member.role }
}

export function attachmentPrincipalHash(userId: string): string {
  return createHash('sha256').update(userId).digest('hex').slice(0, 12)
}
