import { createUIMessageStream, createUIMessageStreamResponse } from 'ai'
import { createHmac } from 'node:crypto'
import { z } from 'zod'
import { useDrizzle, tables, eq, and, inArray } from '../../../utils/drizzle'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams, readValidatedBody } from 'nitro/h3'
import { logMemoryEvent } from '../../../utils/logger'
import { agentFetch } from '../../../utils/agent-client'
import {
  recordAiCall,
  recordMemoryCompaction,
  recordMemoryDuration,
  recordMemoryFact
} from '../../../utils/metrics'
import { requireOwnedChat } from '../../../utils/chatAccess'
import { compactAfterSuccessfulAssistantPersistence } from '../../../utils/postTurnCompaction'
import {
  createFactProposal,
  readCurrentRevisionFactSource
} from '../../../utils/memoryRepository'
import { isSensitiveMemoryValue } from '../../../utils/sensitiveMemoryValue'
import { isSessionFactEnabled } from '../../../utils/sessionFactGate'
import type { FactProposal } from '../../../utils/memoryContract'
import { requireAttachmentAccess } from '../../../utils/attachmentAccess'
import { getOrCreateDefaultLibrary } from '../../../utils/library'
import {
  extractAttachmentSelection,
  mergeSafeAttachmentParts,
} from '../../../../shared/utils/attachmentParts'
import { canSelectAttachmentForChat } from '../../../../shared/utils/attachmentScope'
import { knowledgeBaseRetrievalEnabled } from '../../../../shared/utils/chatRetrieval'
import { chatExplorationMode } from '../../../../shared/utils/chatExploration'
import { buildPersistentMemoryContext } from '../../../utils/persistentMemoryContext'
import { requireCsrf } from '../../../utils/attachmentAuth'
import { assertSourceDependencies, evidenceProvenanceSchema, provenancePart, citationsCovered, type EvidenceProvenance } from '../../../utils/sourceAccess'
import {
  appendMessage,
  createAssistantStreamState,
  createCurrentMessageHandoff,
  persistCurrentUserMessage,
  shouldPersistAssistantMessage
} from '../../../utils/messageLifecycle'

type Database = NonNullable<ReturnType<typeof useDrizzle>>

interface PersistAgentFactProposalsInput {
  evidenceProvenance?: EvidenceProvenance
  actorUserId: string
  chatId: string
  currentMessageId: string
  historyRevision: number
  proposals: FactProposal[]
}

const FACT_CATEGORIES = new Set<FactProposal['category']>([
  'GOAL',
  'PREFERENCE',
  'PLAN_CONSTRAINT'
])

export async function persistAgentFactProposalsAfterAssistantPersistence (
  db: Database,
  input: PersistAgentFactProposalsInput
): Promise<void> {
  if (!isSessionFactEnabled()) {
    recordMemoryFact('suppressed', 'disabled')
    return
  }
  if (input.proposals.length === 0) {
    recordMemoryFact('suppressed', 'empty')
    return
  }

  let source
  try {
    source = await readCurrentRevisionFactSource(db, {
      actorUserId: input.actorUserId,
      chatId: input.chatId,
      historyRevision: input.historyRevision,
      sourceMessageId: input.currentMessageId
    })
  } catch {
    recordMemoryFact('suppressed', 'failed')
    logMemoryEvent({ event: 'memory_fact', action: 'suppressed', outcome: 'failed' })
    return
  }

  if (!source || source.role !== 'user') {
    recordMemoryFact('suppressed', 'failed')
    logMemoryEvent({ event: 'memory_fact', action: 'suppressed', outcome: 'failed' })
    return
  }

  if (input.proposals.length > 1) {
    recordMemoryFact('suppressed', 'failed')
    logMemoryEvent({ event: 'memory_fact', action: 'suppressed', outcome: 'failed' })
  }

  const proposal = input.proposals[0]
  if (!proposal) return
  if (proposal.source_message_id !== input.currentMessageId) {
    recordMemoryFact('suppressed', 'failed')
    logMemoryEvent({ event: 'memory_fact', action: 'suppressed', outcome: 'failed' })
    return
  }
  if (!FACT_CATEGORIES.has(proposal.category)) {
    recordMemoryFact('suppressed', 'failed')
    logMemoryEvent({ event: 'memory_fact', action: 'suppressed', outcome: 'failed' })
    return
  }
  if (!proposal.value.trim()) {
    recordMemoryFact('suppressed', 'empty')
    logMemoryEvent({ event: 'memory_fact', action: 'suppressed', outcome: 'empty' })
    return
  }
  if (isSensitiveMemoryValue(proposal.value)) {
    recordMemoryFact('suppressed', 'sensitive')
    logMemoryEvent({ event: 'memory_fact', action: 'suppressed', outcome: 'sensitive' })
    return
  }

  try {
    await createFactProposal(db, {
      actorUserId: input.actorUserId,
      category: proposal.category,
      chatId: input.chatId,
      historyRevision: input.historyRevision,
      sourceMessageId: input.currentMessageId,
      evidenceProvenance: input.evidenceProvenance,
      value: proposal.value
    })
    recordMemoryFact('proposed', 'success')
    logMemoryEvent({ event: 'memory_fact', action: 'proposed', outcome: 'success' })
  } catch {
    recordMemoryFact('suppressed', 'failed')
    logMemoryEvent({ event: 'memory_fact', action: 'suppressed', outcome: 'failed' })
  }
}

const uiMessageSchema = z.object({
  id: z.string().min(1),
  parts: z.array(z.unknown()),
  role: z.enum(['user', 'assistant', 'system'])
}).passthrough()

export default defineHandler(async (event) => {
  requireCsrf(event)
  const { id } = await getValidatedRouterParams(event, z.object({ id: z.string().min(1) }).parse)
  const { actor, chat } = await requireOwnedChat(event, id, 'editor')
  const body = await readValidatedBody(event, z.object({
    model: z.string().optional(),
    messages: z.array(uiMessageSchema).min(1).max(100),
    weightMode: z.enum(['thinking', 'auto', 'fast']).optional(),
  }).parse)
  const last = body.messages.at(-1)!
  if (last.role !== 'user') throw new HTTPError({ statusCode: 400, statusMessage: 'last_message_must_be_user' })
  const query = last.parts.filter((part: any) => part?.type === 'text').map((part: any) => part.text || '').join('')
  if (!query.trim() || query.length > 16000) throw new HTTPError({ statusCode: 422, statusMessage: 'invalid_query' })
  const metadata = (last as any).metadata || {}
  const selection = extractAttachmentSelection(last.parts, metadata)
  const db = useDrizzle()
  const attachments = []
  for (const attachmentId of selection.attachmentIds) {
    const { attachment } = await requireAttachmentAccess(event, attachmentId)
    if (!canSelectAttachmentForChat(attachment, chat.id, chat.topicId)
      || (attachment.status !== 'ready' && !(attachment.status === 'needs_review' && selection.acceptedNeedsReviewIds.includes(attachment.id)))) {
      throw new HTTPError({ statusCode: 409, statusMessage: 'attachments_not_ready_or_scope_mismatch' })
    }
    attachments.push(attachment)
  }
  const safeParts = mergeSafeAttachmentParts([
    { type: 'text', text: query },
    { type: 'data-chat-preferences', data: {
      knowledge_base_retrieval_enabled: knowledgeBaseRetrievalEnabled(metadata, last.parts),
      exploration_mode: chatExplorationMode(metadata, last.parts),
    } },
  ], attachments, new Set(selection.acceptedNeedsReviewIds))
  const current = await persistCurrentUserMessage(db, { chatId: chat.id, id: last.id, parts: safeParts })
  const handoff = createCurrentMessageHandoff(actor.userId, current)
  const assistantId = `${current.id}:assistant`
  const existing = await db.query.messages.findFirst({ where: and(eq(tables.messages.chatId, chat.id), eq(tables.messages.requestId, current.id), eq(tables.messages.role, 'assistant')) })
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 180000)
  event.runtime?.node?.res?.on('close', () => {
    if (!event.runtime?.node?.res?.writableEnded) controller.abort()
    clearTimeout(timeout)
  })
  const state = createAssistantStreamState()
  let provenance: EvidenceProvenance | undefined
  let citations: any[] = []
  let factProposals: FactProposal[] = []
  let savedAssistant: typeof tables.messages.$inferSelect | undefined
  let chatTitle: string | undefined
  let memoryRecall = false
  let reasoning = ''
  let agentStatus: string | undefined
  const startedAt = Date.now()
  let guardPhase = 'context'
  const stream = createUIMessageStream({
    onError: () => 'The source access or evidence version could not be verified. Please sign in or retry.',
    execute: async ({ writer }) => {
      try {
        if (existing) {
          const { assertMessageSources, messageProvenance } = await import('../../../utils/sourceAccess')
          await assertMessageSources(actor.userId, existing)
          provenance = messageProvenance(existing.parts)
          const parts = Array.isArray(existing.parts) ? existing.parts : []
          state.assistantContent = parts.filter((part: any) => part.type === 'text').map((part: any) => part.text || '').join('')
          citations = parts.flatMap((part: any) => part.type === 'tool-rag_search' ? part.output || [] : [])
        } else {
          const memoryContext = await buildPersistentMemoryContext(db, handoff)
          const topicAttachments = chat.topicId ? await db.query.attachments.findMany({ where: and(
            eq(tables.attachments.topicId, chat.topicId), eq(tables.attachments.scope, 'topic'),
          ) }) : []
          const allowedIds = [...new Set([...selection.attachmentIds, ...topicAttachments.filter(item => item.status === 'ready' && !item.deletedAt).map(item => item.id)])]
          const secret = process.env.ATTACHMENT_INTERNAL_SECRET || ''
          const personalContext = process.env.PERSONAL_LIBRARY_ENABLED === 'true' && secret
            ? await getOrCreateDefaultLibrary(actor.userId).then(library => ({
              owner_user_id: actor.userId, knowledge_base_id: library.id,
              access_token: createHmac('sha256', secret).update(`${actor.userId}:${library.id}`).digest('hex'),
            })) : undefined
          const response = await agentFetch('/api/internal/chat/retrieval/stream', {
            method: 'POST', headers: { 'X-User-ID': actor.userId, 'X-Agent-Internal-Token': process.env.AGENT_INTERNAL_TOKEN || '' },
            body: JSON.stringify({
              query, user_id: actor.userId, session_id: chat.id, top_k: 5, stream: true, retrieval_mode: 'hybrid',
              exploration_mode: chatExplorationMode(metadata, last.parts),
              weight_mode: (chat as any).weightMode || 'thinking', topic_id: chat.topicId || undefined,
              is_first_message: handoff.currentSequence === 1,
              knowledge_base_retrieval_enabled: knowledgeBaseRetrievalEnabled(metadata, last.parts),
              memory_context: memoryContext, personal_library_context: personalContext,
              attachment_context: { selected_attachment_ids: selection.attachmentIds, allowed_attachment_ids: allowedIds },
            }), signal: controller.signal,
          })
          if (!response.ok || !response.body) throw new Error('agent_unavailable')
          guardPhase = 'agent_stream'
          const reader = response.body.getReader()
          const decoder = new TextDecoder()
          let buffer = ''
          let completed = false
          const processFrame = (frame: string) => {
            const lines = frame.split('\n')
            const eventType = lines.find(line => line.startsWith('event:'))?.slice(6).trim() || 'message'
            const value = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
            if (!value) return
            const data = JSON.parse(value)
            if (eventType === 'citations') {
              if (!Array.isArray(data)) throw new Error('invalid_citations')
              citations = data.map((citation: any, index: number) => {
                if (!citation.doc_id || !citation.chunk_id || !citation.evidence_ref || !citation.content_hash) throw new Error('incomplete_citation')
                return { ...citation, index: index + 1, chunk_text: citation.snippet || '' }
              })
            } else if (eventType === 'token') {
              state.assistantContent += String(data.content || '')
              if (state.assistantContent.length > 100000) throw new Error('answer_limit')
            } else if (eventType === 'done') {
              provenance = evidenceProvenanceSchema.parse(data.evidence_provenance)
              agentStatus = data.status
              factProposals = data.memory_decision?.fact_proposals || []
              memoryRecall = data.memory_decision?.recall?.handled === true
              chatTitle = data.chat_title
              state.agentSucceeded = data.status === 'success' || data.status === 'clarification_required'
              completed = true
            } else if (eventType === 'reasoning') reasoning += String(data.content || '')
            else if (eventType === 'error') throw new Error('agent_failed')
          }
          while (true) {
            const chunk = await reader.read()
            buffer += decoder.decode(chunk.value, { stream: !chunk.done }).replace(/\r\n/g, '\n')
            let boundary
            while ((boundary = buffer.indexOf('\n\n')) >= 0) {
              processFrame(buffer.slice(0, boundary)); buffer = buffer.slice(boundary + 2)
            }
            if (chunk.done) { if (buffer.trim()) processFrame(buffer); break }
          }
          if (!completed) throw new Error('incomplete_stream')
          if (!state.agentSucceeded && agentStatus !== 'no_relevant_context') throw new Error('agent_failed')
        }
        if (!provenance?.complete || !citationsCovered(provenance, citations)) throw new Error('source_provenance_incomplete')
        guardPhase = 'current_source_check'
        state.assistantContent = state.assistantContent.replace(/^\s*\[TITLE:[^\]]*\]\s*/i, '')
        await assertSourceDependencies(actor.userId, provenance.dependencies)
        await requireOwnedChat(event, chat.id, 'editor')
        if (controller.signal.aborted) throw new Error('request_aborted')
        if (agentStatus === 'no_relevant_context') {
          // An abstention is a transient UI status, not a durable, sourced answer.
          // Do not expose model tokens/citations or create Memory side effects.
          const statusId = `no-context:${assistantId}`
          writer.write({ type: 'start', messageId: statusId })
          writer.write({ type: 'data-answer-status', data: { status: 'no_relevant_context', persisted: false } } as any)
          writer.write({ type: 'text-start', id: statusId })
          writer.write({ type: 'text-delta', id: statusId, delta: '当前可访问的知识库没有足够证据回答该问题。请补充资料或调整问题。' })
          writer.write({ type: 'text-end', id: statusId })
          state.assistantContent = ''
          state.streamCompleted = true
          return
        }
        if (!existing) {
          guardPhase = 'durable_write'
          savedAssistant = await appendMessage(db, { id: assistantId, chatId: chat.id, role: 'assistant',
            requestId: current.id, parts: [
              { type: 'text', text: state.assistantContent },
              { type: 'tool-rag_search', state: 'output-available', toolCallId: assistantId, input: { query }, output: citations },
              provenancePart(provenance),
            ] })
        }
        // Release only a durable response whose sources still pass after the write.
        guardPhase = 'release_check'
        await assertSourceDependencies(actor.userId, provenance.dependencies)
        await requireOwnedChat(event, chat.id, 'editor')
        writer.write({ type: 'start', messageId: existing?.id || savedAssistant?.id || assistantId })
        if (reasoning) {
          writer.write({ type: 'reasoning-start', id: assistantId })
          writer.write({ type: 'reasoning-delta', id: assistantId, delta: reasoning })
          writer.write({ type: 'reasoning-end', id: assistantId })
        }
        if (citations.length) {
          writer.write({ type: 'tool-input-available', toolCallId: assistantId, toolName: 'rag_search', input: { query } })
          writer.write({ type: 'tool-output-available', toolCallId: assistantId, output: citations })
        }
        writer.write({ type: 'data-evidence-provenance', data: provenance } as any)
        if (memoryRecall) writer.write({ type: 'data-memory-recall', data: { messageId: savedAssistant?.id || assistantId } } as any)
        writer.write({ type: 'text-start', id: assistantId })
        writer.write({ type: 'text-delta', id: assistantId, delta: state.assistantContent })
        writer.write({ type: 'text-end', id: assistantId })
        if (existing) state.agentSucceeded = true
        state.streamCompleted = true
        recordAiCall(Date.now() - startedAt, Date.now() - startedAt, Math.round(state.assistantContent.length * 0.75))
      } catch (error) {
        // Never log source bodies, request payloads, Zod input or credentials.
        console.warn('[chat_access_guard]', { phase: guardPhase,
          errorClass: error instanceof Error ? error.name : 'unknown',
          status: error instanceof HTTPError ? error.status : undefined })
        state.streamFailed = true
        state.assistantContent = ''
        writer.write({ type: 'text-start', id: 'access-error' })
        writer.write({ type: 'text-delta', id: 'access-error', delta: 'The answer could not pass identity, source access, version, or persistence checks. No answer is being released. Please retry.' })
        writer.write({ type: 'text-end', id: 'access-error' })
      } finally { clearTimeout(timeout) }
    },
    onFinish: async ({ isAborted }) => {
      if (isAborted || controller.signal.aborted) state.clientAborted = true
      if (existing || !provenance?.complete || !shouldPersistAssistantMessage(state)) return
      await requireOwnedChat(event, chat.id, 'editor')
      await assertSourceDependencies(actor.userId, provenance.dependencies)
      const assistant = savedAssistant
      if (!assistant) return
      if (chatTitle && handoff.currentSequence === 1) await db.update(tables.chats).set({ title: chatTitle, evidenceProvenance: provenance }).where(eq(tables.chats.id, chat.id))
      if (factProposals.length) await persistAgentFactProposalsAfterAssistantPersistence(db, {
        actorUserId: actor.userId, chatId: chat.id, currentMessageId: current.id,
        historyRevision: assistant.historyRevision, proposals: factProposals,
        evidenceProvenance: provenance,
      })
      // Topic source pools are a view of successfully saved evidence, never
      // side effects of unverified intermediate retrieval frames.
      if (chat.topicId) {
        await assertSourceDependencies(actor.userId, provenance.dependencies)
        for (const citation of citations.filter(item => item.source_type === 'knowledge')) {
          await db.insert(tables.topicDocuments).values({ topicId: chat.topicId, docId: citation.doc_id,
            title: citation.title, sourceUrl: citation.source_url || null, snippet: citation.snippet || '',
          }).onConflictDoNothing()
        }
      }
      try {
        const compactStarted = Date.now()
        const outcome = await compactAfterSuccessfulAssistantPersistence(db, handoff)
        recordMemoryDuration('compaction', Date.now() - compactStarted)
        recordMemoryCompaction(outcome === 'applied' ? 'success' : 'skipped')
      } catch {
        // A post-turn optimization must not turn a durable response into a failed turn.
        recordMemoryCompaction('failed')
      }
    },
  })
  return createUIMessageStreamResponse({ stream })
})
