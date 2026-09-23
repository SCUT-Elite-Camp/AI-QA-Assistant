import type { UIMessage } from 'ai'
import { createUIMessageStream, createUIMessageStreamResponse } from 'ai'
import { z } from 'zod'
import path from 'path'
import fs from 'fs'
import { useDrizzle, tables, eq, and } from '../../../utils/drizzle'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams, readValidatedBody } from 'nitro/h3'
import { logger, logMemoryEvent } from '../../../utils/logger'
import { agentFetch } from '../../../utils/agent-client'
import {
  recordAiCall,
  recordMemoryCompaction,
  recordMemoryDuration,
  recordMemoryFact,
  recordMemoryFallback,
  recordMemoryResolve
} from '../../../utils/metrics'
import { ensureTopicDir, loadTopicFromDisk, syncAllTopicDocuments } from '../../../utils/topicStorage'
import { requireOwnedChat } from '../../../utils/chatAccess'
import { compactAfterSuccessfulAssistantPersistence } from '../../../utils/postTurnCompaction'
import {
  createFactProposal,
  readCurrentRevisionFactSource
} from '../../../utils/memoryRepository'
import { isSensitiveMemoryValue } from '../../../utils/sensitiveMemoryValue'
import { isSessionFactEnabled } from '../../../utils/sessionFactGate'
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

  const { actor, chat } = await requireOwnedChat(event, id)

  const body = await readValidatedBody(event, z.object({
    model: z.string().optional(),
    messages: z.array(uiMessageSchema).min(1),
    weightMode: z.string().optional()
  }).parse)

  const messages = body.messages as UIMessage[]
  const db = useDrizzle()

  const lastMessage = messages[messages.length - 1]
  if (!lastMessage || lastMessage.role !== 'user') {
    throw new HTTPError({ statusCode: 400, statusMessage: 'The last message must be a user message' })
  }

  const queryText = lastMessage.content || (lastMessage as any)?.parts?.[0]?.text || ''

  // Detect if chat needs title (first message turn or placeholder title)
  const messageCount = (chat.messages || []).length
  const needsTitle = messageCount <= 1 || !chat.title || chat.title === '' || chat.title === 'New Chat' || chat.title === 'Untitled' || chat.title === '新对话' || chat.title.endsWith('...')

  const currentMessage = await persistCurrentUserMessage(db, {
    chatId: id as string,
    id: lastMessage.id,
    parts: lastMessage.parts
  })

  if (!currentMessage || currentMessage.role !== 'user') {
    throw new HTTPError({ statusCode: 409, statusMessage: 'Current user message was not persisted' })
  }

  const currentAgentInput = createCurrentMessageHandoff(actor.userId, currentMessage)

  const abortController = new AbortController()
  const assistantState = createAssistantStreamState()
  let assistantMessageId: string | undefined
  let agentFactProposals: FactProposal[] = []
  let shouldAttemptCompaction = false

  const timeoutId = setTimeout(() => abortController.abort(), 90000)
  event.runtime?.node?.req?.on('close', () => {
    clearTimeout(timeoutId)
    assistantState.clientAborted = true
    abortController.abort()
  })

  const stream = createUIMessageStream({
    onError: (err: any) => {
      clearTimeout(timeoutId)
      assistantState.streamFailed = true
      console.error('[web-stream] onError occurred:', err)
      return err.message || 'An error occurred.'
    },
    execute: async ({ writer }) => {
      try {
        let topicInfo: any = null
        let topicDocIds: string[] = []
        let topicTitles: string[] = []
        let soulContent: string | undefined = undefined

        if (chat.topicId) {
          topicInfo = await db.query.topics.findFirst({
            where: eq(tables.topics.id, chat.topicId)
          })
          const diskData = loadTopicFromDisk(chat.topicId)
          soulContent = topicInfo?.soulContent || diskData?.soulContent || undefined

          if (topicInfo || diskData) {
            const topicDocs = await db.query.topicDocuments.findMany({
              where: and(
                eq(tables.topicDocuments.topicId, chat.topicId),
                eq(tables.topicDocuments.isRemoved, false)
              )
            })
            topicDocIds = topicDocs.map(d => d.docId)
            topicTitles = topicDocs.map(d => d.title)
          }
        }

        // 1. Emit tool-input-available event immediately so client tracks real retrieval state
        const toolCallId = `call_${Date.now()}`
        writer.write({
          type: 'tool-input-available',
          toolCallId,
          toolName: 'rag_search',
          input: { query: queryText }
        })

        // 2. Call real Python Agent Streaming API (port 8000)
        const aiCallStart = Date.now()
        const agentRes = await agentFetch("/api/chat/stream", {
          method: "POST",
          body: JSON.stringify({
            query: queryText,
            session_id: currentAgentInput.chatId,
            user_id: actor.userId,
            top_k: 5,
            stream: true,
            retrieval_mode: "hybrid",
            topic_id: chat.topicId || undefined,
            weight_mode: body.weightMode || topicInfo?.weightMode || "thinking",
            soul_content: soulContent || undefined,
            topic_doc_ids: topicDocIds,
            topic_titles: topicTitles,
            consecutive_no_new_docs_count: topicInfo?.consecutiveNoNewDocsCount || 0,
            is_first_message: needsTitle
          }),
          signal: abortController.signal
        })
        clearTimeout(timeoutId)

        if (!agentRes.ok || !agentRes.body) {
          throw new Error(`Failed to contact Agent Layer: ${agentRes.statusText}`)
        }

        const reader = agentRes.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        const reasoningId = `reasoning-${Date.now()}`
        const currentAssistantMessageId = createAssistantMessageId()
        assistantMessageId = currentAssistantMessageId
        const responseId = currentAssistantMessageId

        let hasReasoningStarted = false
        let hasReasoningEnded = false
        let hasTextStarted = false
        let accumulatedAnswer = ''
        let citationsList: any[] = []

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          let currentEvent = ''
          for (const line of lines) {
            const trimmed = line.trim()
            if (!trimmed) continue

            if (trimmed.startsWith('event:')) {
              currentEvent = trimmed.slice(6).trim()
            } else if (trimmed.startsWith('data:')) {
              const dataStr = trimmed.slice(5).trim()
              try {
                const data = JSON.parse(dataStr)

                if (currentEvent === 'citations' || Array.isArray(data)) {
                  citationsList = Array.isArray(data) ? data : (data.citations || [])
                  
                  // Write citations to client
                  writer.write({
                    type: 'tool-output-available',
                    toolCallId,
                    output: citationsList.map((cit: any, i: number) => {
                      let docUpdated = cit.last_updated || null
                      if (!docUpdated && cit.doc_id) {
                        try {
                          const docPath = path.resolve(process.cwd(), `../data-persistence/data/documents/${cit.doc_id}.json`)
                          if (fs.existsSync(docPath)) {
                            const dJson = JSON.parse(fs.readFileSync(docPath, 'utf-8'))
                            docUpdated = dJson.last_updated || null
                          }
                        } catch {}
                      }
                      return {
                        index: i + 1,
                        doc_id: cit.doc_id || `doc_${i}`,
                        chunk_id: cit.chunk_id || `chunk_${i}`,
                        title: cit.title || cit.doc_id || `Document ${i + 1}`,
                        source_url: cit.source_url || `https://local-document/${cit.doc_id}`,
                        chunk_text: cit.snippet || '',
                        score: cit.score ?? null,
                        similarity: cit.vector_score ?? cit.similarity_score ?? null,
                        vector_score: cit.vector_score ?? null,
                        last_updated: docUpdated
                      }
                    })
                  })

                  // If chat belongs to a topic, accumulate citations into topic_documents pool & update counter
                  if (chat.topicId && citationsList.length > 0) {
                    try {
                      let hasNewDocs = false
                      for (const cit of citationsList) {
                        const docId = cit.doc_id || `doc_${Date.now()}`
                        const title = cit.title || docId
                        const snippet = cit.snippet || ''

                        const existingDoc = await db.query.topicDocuments.findFirst({
                          where: and(
                            eq(tables.topicDocuments.topicId, chat.topicId),
                            eq(tables.topicDocuments.docId, docId)
                          )
                        })

                        if (existingDoc) {
                          await db.update(tables.topicDocuments).set({
                            recallCount: existingDoc.recallCount + 1,
                            lastRecalledAt: new Date(),
                            snippet: snippet || existingDoc.snippet
                          }).where(eq(tables.topicDocuments.id, existingDoc.id))
                        } else {
                          hasNewDocs = true
                          await db.insert(tables.topicDocuments).values({
                            topicId: chat.topicId,
                            docId,
                            title,
                            sourceUrl: cit.source_url || null,
                            snippet,
                            recallCount: 1,
                            score: cit.score ? Math.round(cit.score * 100) : null
                          })
                        }

                        // Physical document file persistence directly to data-persistence/data/topics/<topicId>/documents/
                        try {
                          const topicDir = ensureTopicDir(chat.topicId)
                          const docsFolder = path.join(topicDir, 'documents')
                          if (!fs.existsSync(docsFolder)) {
                            fs.mkdirSync(docsFolder, { recursive: true })
                          }
                          const safeTitle = title.replace(/[^a-zA-Z0-9_\-\.\u4e00-\u9fa5]/g, '_')
                          const filePath = path.join(docsFolder, `${docId}_${safeTitle}.txt`)
                          const fileText = `Title: ${title}\nSource: ${cit.source_url || 'RAG Retrieval'}\nScore: ${cit.score || ''}\n\nContent:\n${snippet}`
                          fs.writeFileSync(filePath, fileText, 'utf-8')
                        } catch (fileErr) {
                          console.error('[TopicDocFileSaveError]', fileErr)
                        }
                      }

                      // Update anti-echo-chamber counter & sync to disk folder
                      if (topicInfo) {
                        const newCount = hasNewDocs ? 0 : (topicInfo.consecutiveNoNewDocsCount || 0) + 1
                        await db.update(tables.topics)
                          .set({ consecutiveNoNewDocsCount: newCount })
                          .where(eq(tables.topics.id, chat.topicId))
                      }
                      await syncAllTopicDocuments(db, chat.topicId)
                    } catch (docErr) {
                      console.error('[TopicDocPoolUpdateError]', docErr)
                    }
                  }
                } else if (currentEvent === 'reasoning') {
                  const reasoningDelta = data.content || ''
                  if (reasoningDelta) {
                    if (!hasReasoningStarted) {
                      hasReasoningStarted = true
                      writer.write({
                        type: 'reasoning-start',
                        id: reasoningId
                      })
                    }
                    writer.write({
                      type: 'reasoning-delta',
                      id: reasoningId,
                      delta: reasoningDelta
                    })
                  }
                } else if (currentEvent === 'token') {
                  const tokenDelta = data.content || ''
                  if (tokenDelta) {
                    if (hasReasoningStarted && !hasReasoningEnded) {
                      hasReasoningEnded = true
                      writer.write({
                        type: 'reasoning-end',
                        id: reasoningId
                      })
                    }
                    if (!hasTextStarted) {
                      hasTextStarted = true
                      writer.write({
                        type: 'text-start',
                        id: responseId
                      })
                    }
                    accumulatedAnswer += tokenDelta
                    assistantState.assistantContent += tokenDelta
                    writer.write({
                      type: 'text-delta',
                      id: responseId,
                      delta: tokenDelta
                    })
                  }
                } else if (currentEvent === 'done') {
                  assistantState.agentSucceeded = true
                  const aiDuration = Date.now() - aiCallStart
                  const tokensCount = Math.max(20, Math.round((accumulatedAnswer.length || 0) * 0.75 + (queryText.length || 0) * 0.5))
                  const ttftMs = Math.max(50, Math.round(aiDuration * 0.25))
                  recordAiCall(aiDuration, ttftMs, tokensCount)

                  if (data.chat_title) {
                    await db.update(tables.chats).set({ title: data.chat_title }).where(eq(tables.chats.id, id as string))
                    writer.write({
                      type: 'data-chat-title',
                      data: { title: data.chat_title }
                    })
                  }
                } else if (currentEvent === 'error') {
                  const errMsg = data.message || 'Stream processing error'
                  throw new Error(errMsg)
                }
              } catch (parseErr: any) {
                if (currentEvent === 'error' || parseErr?.message?.includes('Stream processing error') || parseErr?.message?.includes('validation error')) {
                  throw parseErr
                }
                console.error('[SSE parse error]', parseErr, line)
              }
            }
          }
        }

        if (hasReasoningStarted && !hasReasoningEnded) {
          writer.write({
            type: 'reasoning-end',
            id: reasoningId
          })
        }

        if (hasTextStarted) {
          writer.write({
            type: 'text-end',
            id: responseId
          })
          assistantState.streamCompleted = true
        }
      } catch (err: any) {
        assistantState.streamFailed = true
        console.error('[web-post] error in agent call:', err)
        const responseId = `err-msg-${Date.now()}`
        const isTimeout = err.name === 'AbortError' || err.message?.includes('aborted') || err.message?.includes('timeout')
        const msg = isTimeout 
          ? `目前远端大模型响应超时，但知识库检索引擎仍正常运行。请稍后再试或精简提问。`
          : `响应生成受阻：${err.message || '网络连接中断'}`

        writer.write({
          type: 'text-start',
          id: responseId
        })
        writer.write({
          type: 'text-delta',
          id: responseId,
          delta: msg
        })
        writer.write({
          type: 'text-end',
          id: responseId
        })
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
            recordMemoryCompaction('failed')
            logMemoryEvent({ event: 'memory_compaction', outcome: 'failed' })
          } finally {
            recordMemoryDuration('compaction', Date.now() - compactionStartedAt)
          }
        }
      } catch (persistErr) {
        assistantState.streamFailed = true
        console.error('[web-onFinish] assistant message persistence failed:', persistErr)
      }
    }
  })

  return createUIMessageStreamResponse({
    stream
  })
})

