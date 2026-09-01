import type { UIMessage } from 'ai'
import { createUIMessageStream, createUIMessageStreamResponse } from 'ai'
import { z } from 'zod'
import { useDrizzle, tables, eq, and } from '../../../utils/drizzle'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams, readValidatedBody } from 'nitro/h3'
import { MODELS } from '../../../../shared/utils/models'
import { logger } from '../../../utils/logger'
import { agentFetch } from '../../../utils/agent-client'
import { recordAiCall } from '../../../utils/metrics'
import {
  recordAiCall,
  recordMemoryCompaction,
  recordMemoryDuration,
  recordMemoryFact,
  recordMemoryFallback,
  recordMemoryResolve
} from '../../../utils/metrics'
import { syncTopicToDisk, ensureTopicDir } from '../../../utils/topicStorage'
import { getAgentBaseUrl, requireOwnedChat } from '../../../utils/chatAccess'
import { callChatWithPersistentFallback, shouldUsePersistentMemory } from '../../../utils/agentInternalClient'
import { compactAfterSuccessfulAssistantPersistence } from '../../../utils/postTurnCompaction'
import { buildPersistentMemoryContext } from '../../../utils/persistentMemoryContext'
import {
  createFactProposal,
  readCurrentRevisionFactSource
} from '../../../utils/memoryRepository'
import { isSensitiveMemoryValue } from '../../../utils/sensitiveMemoryValue'
import { isSessionFactEnabled } from '../../../utils/sessionFactGate'
import { logMemoryEvent } from '../../../utils/logger'
import type { FactProposal } from '../../../utils/memoryContract'
import {
  appendMessage,
  createAssistantMessageId,
  createAssistantStreamState,
  createCurrentMessageHandoff,
  persistCurrentUserMessage,
  shouldPersistAssistantMessage
} from '../../../utils/messageLifecycle'

type Database = NonNullable<ReturnType<typeof useDrizzle>>

interface PersistAgentFactProposalsInput {
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

/**
 * This server-only best-effort branch runs only after the assistant row is
 * durable. It intentionally absorbs malformed Agent candidates and storage
 * errors so neither condition can change an already successful chat response.
 */
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
    // expires_at from the internal envelope is deliberately ignored. The
    // Repository is the only component that assigns expiry on confirmation.
    await createFactProposal(db, {
      actorUserId: input.actorUserId,
      category: proposal.category,
      chatId: input.chatId,
      historyRevision: input.historyRevision,
      sourceMessageId: input.currentMessageId,
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
  const { id } = await getValidatedRouterParams(event, z.object({
    id: z.string()
  }).parse)

  const { model, messages } = await readValidatedBody(event, z.object({
    model: z.string().refine(value => MODELS.some(m => m.value === value), {
      message: 'Invalid model'
    }),
    messages: z.array(z.custom<UIMessage>())
  }).parse)

  // Authorize before reading the request body, writing a user message, or
  // calling the Agent so a supplied chat ID can never cross ownership bounds.
  const { actor } = await requireOwnedChat(event, id)

  const body = await readValidatedBody(event, z.object({
    model: z.string().optional(),
    messages: z.array(uiMessageSchema).min(1)
  }).parse)

  const messages = body.messages as UIMessage[]

  const db = useDrizzle()

  const chat = await db.query.chats.findFirst({
    where: (chat, { eq }) => and(eq(chat.id, id as string), eq(chat.userId, session.data.user?.id || session.id!)),
    with: {
      messages: {
        orderBy: (message, { asc }) => asc(message.sequence)
      }
    }
  })
  if (!chat) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Chat not found' })
  }

  // Generate title locally from first message to avoid external API calls
  if (!chat.title) {
    const firstMsgText = messages[0]?.content || 'New Chat'
    const title = firstMsgText.length > 25 ? firstMsgText.slice(0, 25) + '...' : firstMsgText
    await db.update(tables.chats).set({ title }).where(eq(tables.chats.id, id as string))
  }

  const lastMessage = messages[messages.length - 1]
  if (lastMessage?.role === 'user' && messages.length > 1) {
    await db.insert(tables.messages).values({
      id: lastMessage.id,
      chatId: id as string,
      role: 'user',
      parts: lastMessage.parts
    }).onConflictDoUpdate({ target: tables.messages.id, set: { parts: lastMessage.parts } })
  if (!lastMessage || lastMessage.role !== 'user') {
    throw new HTTPError({ statusCode: 400, statusMessage: 'The last message must be a user message' })
  }

  const queryText = lastMessage.content || (lastMessage as any)?.parts?.[0]?.text || ''

  // Detect if chat needs title (first message turn or placeholder title)
  const messageCount = (chat.messages || []).length
  const needsTitle = messageCount <= 1 || !chat.title || chat.title === '' || chat.title === 'New Chat' || chat.title === 'Untitled' || chat.title === '新对话' || chat.title.endsWith('...')

  // Always resolve the Agent handoff from the exact body message. For the
  // initial hydrated turn this returns the existing row; for a direct or
  // retried request it persists or reuses that same UI message ID.
  const currentMessage = await persistCurrentUserMessage(db, {
    chatId: id as string,
    id: lastMessage.id,
    parts: lastMessage.parts
  })

  if (!currentMessage || currentMessage.role !== 'user') {
    throw new HTTPError({ statusCode: 409, statusMessage: 'Current user message was not persisted' })
  }

  // This trusted handoff stays server-only until Unit 04/04a maps it to the
  // token-protected memory_context contract. It must not enter public /api/chat.
  const currentAgentInput = createCurrentMessageHandoff(actor.userId, currentMessage)

  const abortController = new AbortController()
  const assistantState = createAssistantStreamState()
  let assistantMessageId: string | undefined
  let agentFactProposals: FactProposal[] = []
  let shouldAttemptCompaction = false
  event.runtime?.node?.req?.on('close', () => {
    assistantState.clientAborted = true
    abortController.abort()
  })

  const stream = createUIMessageStream({
    onError: () => {
      assistantState.streamFailed = true
      console.error('[web-stream] onError occurred')
      return 'Request failed.'
    },
    execute: async ({ writer }) => {
      try {
        const queryText = lastMessage?.content || (lastMessage as any)?.parts?.[0]?.text || ''
        console.log("[DEBUG queryText]", queryText)
        
        // Write a transient status so the user knows RAG is searching
        if (!chat.title) {
          writer.write({
            type: 'data-chat-title',
            data: { message: 'Generating title...' },
            transient: true
        // Fetch Topic Space context if chat is linked to a topic
        let topicInfo: any = null
        let topicDocIds: string[] = []
        let topicTitles: string[] = []
        if (chat.topicId) {
          topicInfo = await db.query.topics.findFirst({
            where: eq(tables.topics.id, chat.topicId)
          })
        }

        // 1. Call real Python Agent API (port 8000)
        const aiCallStart = Date.now()
        const agentRes = await agentFetch("/api/chat", {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            query: queryText,
            top_k: 5,
            retrieval_mode: "hybrid",
            user_id: session.data.user?.id || session.id
          }),
          signal: abortController.signal
        // 1. Call the public Agent API, or the token-protected Memory API only
        // after an authenticated user's exact current message is persisted.
        const aiCallStart = Date.now()
        const publicAgentRequest = {
          query: queryText,
          session_id: currentAgentInput.chatId,
          top_k: 5,
          stream: false,
          retrieval_mode: 'hybrid',
          topic_id: chat.topicId || undefined,
          weight_mode: topicInfo?.weightMode || 'auto',
          soul_content: topicInfo?.soulContent || undefined,
          topic_doc_ids: topicDocIds,
          topic_titles: topicTitles,
          consecutive_no_new_docs_count: topicInfo?.consecutiveNoNewDocsCount || 0,
          is_first_message: needsTitle
        }
        const callPublicAgent = async () => {
          const agentRes = await fetch(`${getAgentBaseUrl()}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(publicAgentRequest),
            signal: abortController.signal
          })
          if (!agentRes.ok) {
            throw new Error(`Failed to contact Agent Layer: ${agentRes.statusText}`)
          }
          return agentRes.json()
        }

        let usePersistentMemory = shouldUsePersistentMemory(actor.isAuthenticated)
        let memoryContext
        if (usePersistentMemory) {
          const contextStartedAt = Date.now()
          try {
            memoryContext = await buildPersistentMemoryContext(db, currentAgentInput)
            recordMemoryResolve('trusted_context', 'success')
            logMemoryEvent({ event: 'memory_resolve', source: 'trusted_context', outcome: 'success' })
          } catch {
            usePersistentMemory = false
            recordMemoryResolve('trusted_context', 'rejected')
            recordMemoryFallback('context_error')
            logMemoryEvent({ event: 'memory_resolve', source: 'trusted_context', outcome: 'rejected' })
            logMemoryEvent({ event: 'memory_fallback', reason: 'context_error' })
          } finally {
            recordMemoryDuration('context', Date.now() - contextStartedAt)
          }
        } else {
          recordMemoryResolve(actor.isAuthenticated ? 'legacy' : 'disabled', 'fallback')
          logMemoryEvent({ event: 'memory_resolve', source: actor.isAuthenticated ? 'legacy' : 'disabled', outcome: 'fallback' })
        }
        const { soul_content: _soulContent, ...internalAgentFields } = publicAgentRequest
        const agentCall = await callChatWithPersistentFallback({
          usePersistentMemory,
          internalRequest: {
            ...internalAgentFields,
            memory_context: memoryContext!
          },
          callPublic: callPublicAgent,
          onFallback: (reason) => {
            recordMemoryFallback(reason)
            logMemoryEvent({ event: 'memory_fallback', reason })
          },
          options: { signal: abortController.signal }
        })
        recordMemoryDuration('internal_chat', Date.now() - aiCallStart)
        const agentData = agentCall.value
        shouldAttemptCompaction = agentCall.source === 'internal'
          && agentData.response.status === 'success'
        if (agentCall.source === 'internal' && agentData.response.status === 'success') {
          agentFactProposals = agentData.memory_decision.fact_proposals
        }
        // A recall label is a trusted UI signal, never a model-generated
        // citation. Only the token-protected internal response may set it.
        const isTrustedMemoryRecall = agentCall.source === 'internal'
          && agentData.memory_decision.recall?.handled === true
        const responseData = agentCall.source === 'internal' ? agentData.response : agentData
        recordAiCall(Date.now() - aiCallStart)

        if (agentData.status !== "success") {
          const errMsg = agentData.message || "RAG retrieval error from Agent layer"
          const responseId = `err-msg-${Date.now()}`
        if (responseData.chat_title) {
          await db.update(tables.chats).set({ title: responseData.chat_title }).where(eq(tables.chats.id, id as string))
          writer.write({
            type: 'data-chat-title',
            data: { title: responseData.chat_title }
          })
        }

        const isNoRelevantContext = responseData.status === 'no_relevant_context'
        const isValidResponse = responseData.status === 'success'
          || responseData.status === 'clarification_required'
          || isNoRelevantContext
        if (!isValidResponse) {
          assistantState.streamFailed = true
          writer.write({
            type: 'error',
            errorText: 'Agent request failed.'
          })
          return
        }

        const rawAnswer = agentData.answer || ""
        const citationsList: any[] = agentData.citations || []
        const rawAnswer = responseData.answer || responseData.message
          || (isNoRelevantContext ? '未找到可用的知识库内容，请补充问题或调整检索范围。' : '')
        // NO_RELEVANT_CONTEXT is a safe user-visible retrieval outcome, not
        // evidence. It must not produce RAG, Fact, recall, or compaction side effects.
        const citationsList: any[] = isNoRelevantContext ? [] : (responseData.citations || [])
        assistantState.agentSucceeded = true
        const currentAssistantMessageId = createAssistantMessageId()
        assistantMessageId = currentAssistantMessageId

        if (isTrustedMemoryRecall && !isNoRelevantContext) {
          writer.write({
            type: 'data-memory-recall',
            data: { messageId: currentAssistantMessageId }
          })
        }

        // 2. Replace [N] markers with :cite-mark{index="N"} — only pass index.
        //    Complex attribute values (chunk text) break MDC {…} parsing when
        //    they contain }, ", or other special characters. Chunk details are
        //    delivered via tool-output and picked up by provide/inject instead.
        let processedAnswer = rawAnswer
        for (let i = 0; i < citationsList.length; i++) {
          const idx = i + 1
          processedAnswer = processedAnswer.split(`[${idx}]`).join(` :cite-mark{index="${idx}"}`)
        }


        // 3. Write RAG search tool invocation — full ChunkCitation array in output.
        //    Sources.vue deduplicates by doc_id; CiteMark looks up by index.
        const toolCallId = `call_${Date.now()}`
        writer.write({
          type: 'tool-input-available',
          toolCallId,
          toolName: 'rag_search',
          input: { query: queryText }
        })

        // 3. Expose a RAG tool invocation only when the Agent supplied
        //    citations. In particular, a deterministic Fact recall must not
        //    be presented as a knowledge-base search.
        if (citationsList.length > 0) {
          const toolCallId = `call_${Date.now()}`
          writer.write({
            type: 'tool-input-available',
            toolCallId,
            toolName: 'rag_search',
            input: { query: queryText }
          })

          writer.write({
            type: 'tool-output-available',
            toolCallId,
            output: citationsList.map((cit: any, i: number) => ({
              index: i + 1,
              doc_id: cit.doc_id || `doc_${i}`,
              chunk_id: cit.chunk_id || `chunk_${i}`,
              title: cit.title || cit.doc_id || `Document ${i + 1}`,
              source_url: cit.source_url || `https://local-document/${cit.doc_id}`,
              chunk_text: cit.snippet || '',
              score: cit.score ?? null,
            }))
          })
        }


        // 4. Stream answer text chunk-by-chunk to simulate real-time typing
        writer.write({
          type: 'text-start',
          id: currentAssistantMessageId
        })

        const chunkSize = 2
        for (let i = 0; i < processedAnswer.length; i += chunkSize) {
          if (abortController.signal.aborted) {
            assistantState.clientAborted = true
            return
          }

          const chunk = processedAnswer.slice(i, i + chunkSize)
          writer.write({
            type: 'text-delta',
            id: currentAssistantMessageId,
            delta: chunk
          })
          assistantState.assistantContent += chunk
          // Small delay for natural streaming pacing
          await new Promise((resolve) => setTimeout(resolve, 20))
        }

        if (abortController.signal.aborted) {
          assistantState.clientAborted = true
          return
        }
        writer.write({
          type: 'text-end',
          id: currentAssistantMessageId
        })
        assistantState.streamCompleted = true

      } catch {
        assistantState.streamFailed = true
        console.error('[web-post] error in agent call')
        if (abortController.signal.aborted) {
          assistantState.clientAborted = true
          return
        }

        try {
          writer.write({
            type: 'error',
            errorText: 'Failed to retrieve an answer from the Agent layer.'
          })
        } catch {
          console.error('[web-post] unable to write stream error')
        }
      }
    },
    onFinish: async ({ isAborted }) => {
      if (isAborted || abortController.signal.aborted) {
        assistantState.clientAborted = true
      }

      if (!assistantMessageId || !shouldPersistAssistantMessage(assistantState)) {
        return
      }

      try {
        const persistedAssistant = await appendMessage(db, {
          id: assistantMessageId,
          chatId: chat.id,
          parts: [{ type: 'text', text: assistantState.assistantContent }],
          role: 'assistant'
        })
        if (shouldAttemptCompaction) {
          await persistAgentFactProposalsAfterAssistantPersistence(db, {
            actorUserId: actor.userId,
            chatId: chat.id,
            currentMessageId: currentAgentInput.currentMessageId,
            historyRevision: persistedAssistant.historyRevision,
            proposals: agentFactProposals
          })
        }
        if (shouldAttemptCompaction) {
          const compactionStartedAt = Date.now()
          try {
            const compactionResult = await compactAfterSuccessfulAssistantPersistence(db, currentAgentInput)
            recordMemoryCompaction(
              compactionResult === 'applied'
                ? 'planned'
                : compactionResult === 'conflict_exhausted'
                  ? 'conflict'
                  : 'skipped'
            )
          } catch {
            // Snapshot planning is best-effort and must never affect this answer.
            recordMemoryCompaction('failed')
            logMemoryEvent({ event: 'memory_compaction', outcome: 'failed' })
          } finally {
            recordMemoryDuration('compaction', Date.now() - compactionStartedAt)
          }
        }
      } catch {
        assistantState.streamFailed = true
        console.error('[web-onFinish] assistant message persistence failed')
      }
    }
  })

  return createUIMessageStreamResponse({
    stream
  })
})
