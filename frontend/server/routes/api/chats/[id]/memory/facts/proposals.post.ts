import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams, readValidatedBody } from 'nitro/h3'
import { useDrizzle } from '../../../../../../utils/drizzle'
import { requireOwnedChat } from '../../../../../../utils/chatAccess'
import {
  MemoryRepositoryError,
  createFactProposal,
  readCurrentRevisionFactSource,
  toFactView
} from '../../../../../../utils/memoryRepository'
import { manualFactProposalRequestSchema } from '../../../../../../utils/memoryContract'
import { isSensitiveMemoryValue } from '../../../../../../utils/sensitiveMemoryValue'
import { isSessionFactEnabled } from '../../../../../../utils/sessionFactGate'

function factError (status: number, code: string, message: string): Response {
  return Response.json({ code, message }, { status })
}

function sourceText (parts: unknown): string {
  if (typeof parts === 'string') return parts
  if (!Array.isArray(parts)) return ''

  return parts
    .filter((part): part is { type: 'text', text: string } => (
      Boolean(part)
      && typeof part === 'object'
      && (part as { type?: unknown }).type === 'text'
      && typeof (part as { text?: unknown }).text === 'string'
    ))
    .map(part => part.text)
    .join('')
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

  let body: { category: 'GOAL' | 'PREFERENCE' | 'PLAN_CONSTRAINT', source_message_id: string }
  try {
    body = await readValidatedBody(event, manualFactProposalRequestSchema.parse)
  } catch {
    return factError(422, 'fact_source_not_user_message', 'Fact proposal must name a current user message and valid category')
  }

  const db = useDrizzle()
  let source
  try {
    source = await readCurrentRevisionFactSource(db, {
      actorUserId: owned.actor.userId,
      chatId: id,
      historyRevision: owned.chat.historyRevision,
      sourceMessageId: body.source_message_id
    })
  } catch (error) {
    if (error instanceof MemoryRepositoryError) {
      return factError(404, 'not_found', 'Not found')
    }
    throw error
  }

  if (!source) return factError(404, 'not_found', 'Not found')
  if (source.role !== 'user') {
    return factError(422, 'fact_source_not_user_message', 'Fact source must be a user message')
  }

  const value = sourceText(source.parts).trim()
  if (!value) {
    return factError(422, 'fact_source_not_user_message', 'Fact source must be a non-empty user message')
  }
  if (isSensitiveMemoryValue(value)) {
    return factError(422, 'fact_sensitive', 'Fact source contains sensitive content')
  }

  try {
    const result = await createFactProposal(db, {
      actorUserId: owned.actor.userId,
      category: body.category,
      chatId: id,
      historyRevision: owned.chat.historyRevision,
      sourceMessageId: source.id,
      value
    })
    return Response.json({ created: result.created, fact: toFactView(result.fact) }, {
      status: result.created ? 201 : 200
    })
  } catch (error) {
    if (error instanceof MemoryRepositoryError) {
      return factError(404, 'not_found', 'Not found')
    }
    throw error
  }
})
