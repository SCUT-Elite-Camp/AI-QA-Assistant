import { HTTPError } from 'nitro'
import type { HTTPEvent } from 'nitro/h3'
import { useDrizzle } from './drizzle'
import { useUserSession } from './session'

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
export async function requireOwnedChat (event: HTTPEvent, chatId: string) {
  const actor = await getOptionalChatActor(event)
  if (!actor) {
    throw new HTTPError({ statusCode: 401, statusMessage: 'Authentication required' })
  }

  const chat = await useDrizzle().query.chats.findFirst({
    where: (chats, { and, eq }) => and(
      eq(chats.id, chatId),
      eq(chats.userId, actor.userId)
    )
  })

  if (!chat) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Chat not found' })
  }

  return { actor, chat }
}

/**
 * Resolves the server-to-server Agent URL. A local fallback is permitted only
 * during development; deployed environments must configure AGENT_BASE_URL.
 */
export function getAgentBaseUrl (): string {
  return resolveAgentBaseUrl(process.env)
}

export function resolveAgentBaseUrl (environment: Record<string, string | undefined>): string {
  const configuredUrl = environment.AGENT_BASE_URL?.trim()
  if (configuredUrl) return configuredUrl.replace(/\/+$/, '')

  if (environment.NODE_ENV === 'development') {
    return 'http://127.0.0.1:8000'
  }

  throw new Error('AGENT_BASE_URL must be configured outside development')
}

/**
 * Token delivery is deliberately deferred until Unit 04a creates token-checked
 * private Agent endpoints. The legacy public chat/reset endpoints must not be
 * treated as a token-protected security boundary.
 */
export function getAgentInternalToken (environment: Record<string, string | undefined> = process.env): string | undefined {
  return environment.AGENT_INTERNAL_TOKEN?.trim() || undefined
}
