import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams } from 'nitro/h3'
import { useDrizzle } from '../../../../../utils/drizzle'
import { requireOwnedChat } from '../../../../../utils/chatAccess'
import {
  MemoryRepositoryError,
  getCurrentRevisionFacts,
  toFactView
} from '../../../../../utils/memoryRepository'
import { isSessionFactEnabled } from '../../../../../utils/sessionFactGate'

function factError (status: number, code: string, message: string): Response {
  return Response.json({ code, message }, { status })
}

export default defineHandler(async (event) => {
  let id: string
  try {
    ({ id } = await getValidatedRouterParams(event, z.object({ id: z.string().min(1) }).parse))
  } catch {
    return factError(404, 'not_found', 'Not found')
  }

  let owned: Awaited<ReturnType<typeof requireOwnedChat>>
  try {
    owned = await requireOwnedChat(event, id)
  } catch (error) {
    if (error instanceof HTTPError) {
      if (error.statusCode === 404) return factError(404, 'not_found', 'Not found')
      if (error.statusCode === 401) return factError(409, 'session_fact_disabled', 'Session Fact is disabled')
    }
    throw error
  }

  // Anonymous sessions retain ordinary chat support, but Fact persistence is
  // intentionally unavailable without an authenticated, deletable owner.
  if (!owned.actor.isAuthenticated || !isSessionFactEnabled()) {
    return factError(409, 'session_fact_disabled', 'Session Fact is disabled')
  }

  try {
    const facts = await getCurrentRevisionFacts(useDrizzle(), {
      actorUserId: owned.actor.userId,
      chatId: id,
      historyRevision: owned.chat.historyRevision
    })
    return { facts: facts.map(toFactView) }
  } catch (error) {
    if (error instanceof MemoryRepositoryError) {
      return factError(404, 'not_found', 'Not found')
    }
    throw error
  }
})
