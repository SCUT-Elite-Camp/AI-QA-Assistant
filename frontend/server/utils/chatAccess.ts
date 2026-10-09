import { HTTPError } from 'nitro'
import type { HTTPEvent } from 'nitro/h3'
import { useDrizzle } from './drizzle'
import { useUserSession } from './session'
import { requireEnabledActor } from './sourceAccess'

export interface ChatActor {
  userId: string
  isAuthenticated: boolean
}

export interface ServerSessionIdentity {
  id?: string
  data: {
    user?: {
      id?: string
    }
  }
}

export function resolveChatActor (session: ServerSessionIdentity): ChatActor | undefined {
  const authenticatedUserId = session.data.user?.id
  const userId = authenticatedUserId || session.id

  if (!userId) return undefined

  return {
    userId,
    isAuthenticated: Boolean(authenticatedUserId)
  }
}

export function requireAuthenticatedActorId (session: ServerSessionIdentity): string {
  const userId = session.data.user?.id

  if (!userId) {
    throw new HTTPError({ statusCode: 401, statusMessage: 'Authentication required' })
  }

  return userId
}

export function isChatOwnedByActor (chatUserId: string, actor: ChatActor): boolean {
  return chatUserId === actor.userId
}

/**
 * Resolves the actor exclusively from the server-side session. Anonymous chat
 * sessions remain supported, but callers that handle persistent memory Facts
 * must use requireActor instead.
 */
export async function getOptionalChatActor (event: HTTPEvent): Promise<ChatActor | undefined> {
  const session = await useUserSession(event)
  return resolveChatActor(session)
}

/**
 * Requires a signed-in user. Future Fact endpoints must use this helper so
 * anonymous browser sessions can never create, read, confirm, or recall Facts.
 */
export async function requireActor (event: HTTPEvent): Promise<string> {
  const session = await useUserSession(event)
  return requireAuthenticatedActorId(session)
}

/**
 * Looks up the chat and its owner in a single query. Missing chats and chats
 * owned by a different session both return 404 to avoid existence disclosure.
 */
export async function requireOwnedChat (event: HTTPEvent, chatId: string, minimumTopicRole: 'viewer' | 'editor' = 'viewer') {
  const actor: ChatActor = { userId: await requireEnabledActor(event), isAuthenticated: true }

  const chat = await useDrizzle().query.chats.findFirst({
    where: (chats, { eq }) => eq(chats.id, chatId)
  })

  if (!chat) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Chat not found' })
  }

  if (chat.topicId) {
    const { requireTopicRole } = await import('./attachmentAuth')
    // Even the original creator must still be a current workspace member.
    await requireTopicRole(event, chat.topicId, minimumTopicRole)
  }
  if (chat.userId !== actor.userId) {
    if (!chat.topicId || chat.id.startsWith('research-')) {
      throw new HTTPError({ statusCode: 404, statusMessage: 'Chat not found' })
    }
  }

  await assertResearchChatAccess(event, chatId)

  return { actor, chat }
}

/** A cached Research transcript remains subject to its current document ACL. */
export async function assertResearchChatAccess(event: HTTPEvent, chatId: string): Promise<void> {
  const seen = new Set<string>()
  let current: string | undefined = chatId
  while (current) {
    if (seen.has(current) || seen.size >= 64) throw new HTTPError({ statusCode: 409, statusMessage: 'Invalid chat ancestry' })
    seen.add(current)
    if (/^research-[a-zA-Z0-9]+$/.test(current)) {
      const { requireResearchActor, fetchResearchBackend } = await import('./researchBackend')
      const userId = await requireResearchActor(event)
      const response = await fetchResearchBackend(userId, `jobs/${current}`)
      if (!response.ok) throw new HTTPError({ statusCode: response.status, statusMessage: 'Research access unavailable' })
      return
    }
    const parent = await useDrizzle().query.chats.findFirst({
      where: (chats, { eq }) => eq(chats.id, current!), columns: { parentChatId: true },
    })
    current = parent?.parentChatId ?? undefined
  }
}
