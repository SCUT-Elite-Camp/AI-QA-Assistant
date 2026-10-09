import type { UIMessage } from 'ai'
import { createUIMessageStream, createUIMessageStreamResponse } from 'ai'
import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { readValidatedBody } from 'nitro/h3'
import { requireCsrf, requirePrincipal, requireTopicRole } from '../../../utils/attachmentAuth'
import { agentFetch } from '../../../utils/agent-client'
import { authoredProvenance, assertDerivedSources, assertMessageSources, evidenceProvenanceSchema, citationsCovered, provenancePart } from '../../../utils/sourceAccess'
import { requireOwnedChat } from '../../../utils/chatAccess'
import { tables, useDrizzle, eq, and } from '../../../utils/drizzle'
import { appendMessage, createCurrentMessageHandoff, persistCurrentUserMessage } from '../../../utils/messageLifecycle'
import { buildPersistentMemoryContext } from '../../../utils/persistentMemoryContext'

/** Selection exploration is an isolated server-owned conversation, not client-supplied memory. */
export default defineHandler(async (event) => {
  requireCsrf(event)
  const userId = await requirePrincipal(event)
  const body = await readValidatedBody(event, z.object({
    messages: z.array(z.custom<UIMessage>()).max(100),
    tempChatId: z.string().optional(),
    selectedText: z.string().max(4000).optional(),
    contextText: z.string().max(16000).optional(), topicId: z.string().optional(),
  }).parse)
  if (body.topicId) await requireTopicRole(event, body.topicId, 'viewer')
  const last = body.messages.at(-1)
  if (last?.role !== 'user' || !last.id || !Array.isArray(last.parts)) {
    throw new HTTPError({ statusCode: 422, statusMessage: 'user_question_required' })
  }
  const text = last.parts.filter((part: any) => part.type === 'text').map((part: any) => String(part.text || '')).join('')
  const query = [text, body.selectedText ? 'User-selected phrase (not source evidence): ' + body.selectedText : ''].filter(Boolean).join('\n')
  if (!query.trim() || query.length > 16000) throw new HTTPError({ statusCode: 422, statusMessage: 'invalid_query' })
  const db = useDrizzle()
  let chat
  if (body.tempChatId) {
    const owned = await requireOwnedChat(event, body.tempChatId)
    if (!owned.chat.isBranch || owned.chat.parentChatId || owned.chat.topicId) {
      throw new HTTPError({ statusCode: 409, statusMessage: 'isolated_chat_required' })
    }
    chat = owned.chat
  } else {
    ;[chat] = await db.insert(tables.chats).values({ title: '划词探索', userId,
      visibility: 'private', isBranch: true, evidenceProvenance: authoredProvenance() }).returning()
  }
  if (!chat) throw new HTTPError({ statusCode: 500, statusMessage: 'chat_create_failed' })
  const current = await persistCurrentUserMessage(db, { chatId: chat.id, id: last.id, parts: [{ type: 'text', text: query }] })
  let saved = await db.query.messages.findFirst({ where: and(eq(tables.messages.chatId, chat.id),
    eq(tables.messages.requestId, current.id), eq(tables.messages.role, 'assistant')) })
  if (!saved) {
    const memory = await buildPersistentMemoryContext(db, createCurrentMessageHandoff(userId, current))
    const response = await agentFetch('/api/internal/chat', { method: 'POST', redirect: 'error',
      headers: { 'X-User-ID': userId, 'X-Agent-Internal-Token': process.env.AGENT_INTERNAL_TOKEN || '' },
      body: JSON.stringify({ query, user_id: userId, session_id: chat.id, weight_mode: 'fast',
        retrieval_mode: 'hybrid', memory_context: memory }),
    })
    if (!response.ok) throw new HTTPError({ statusCode: response.status, statusMessage: 'agent_unavailable' })
    const answer = (await response.json() as any).response
    const proof = evidenceProvenanceSchema.parse(answer.evidence_provenance)
    if (!['success', 'clarification_required'].includes(answer.status) || !citationsCovered(proof, answer.citations || [])) {
      throw new HTTPError({ statusCode: 409, statusMessage: 'unverified_answer' })
    }
    await requireOwnedChat(event, chat.id)
    await assertDerivedSources(userId, proof)
    saved = await appendMessage(db, { chatId: chat.id, requestId: current.id, role: 'assistant', parts: [
      { type: 'text', text: answer.answer || answer.message || '' },
      { type: 'tool-rag_search', toolCallId: current.id, state: 'output-available', input: { query },
        output: (answer.citations || []).map((citation: any, index: number) => ({ ...citation, index: index + 1, chunk_text: citation.snippet || '' })) },
      provenancePart(proof),
    ] })
  }
  await assertMessageSources(userId, saved)
  const message = saved
  const chatId = chat.id
  const stream = createUIMessageStream({ execute: async ({ writer }) => {
    await requireOwnedChat(event, chatId)
    await assertMessageSources(userId, message)
    writer.write({ type: 'start', messageId: message.id })
    writer.write({ type: 'data-temp-chat', data: { chatId } } as any)
    for (const part of message.parts as any[]) {
      if (part.type === 'tool-rag_search' && part.output.length) {
        writer.write({ type: 'tool-input-available', toolCallId: message.id, toolName: 'rag_search', input: part.input })
        writer.write({ type: 'tool-output-available', toolCallId: message.id, output: part.output })
      } else if (part.type === 'data-evidence-provenance') {
        writer.write(part)
      } else if (part.type === 'text') {
        writer.write({ type: 'text-start', id: message.id })
        writer.write({ type: 'text-delta', id: message.id, delta: part.text })
        writer.write({ type: 'text-end', id: message.id })
      }
    }
  } })
  return createUIMessageStreamResponse({ stream })
})
