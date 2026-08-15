import fs from 'fs'
import path from 'path'
import type { UIMessage } from 'ai'
import { createUIMessageStream, createUIMessageStreamResponse } from 'ai'
import { z } from 'zod'
import { useDrizzle, tables, eq, and } from '../../../utils/drizzle'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams, readValidatedBody } from 'nitro/h3'
import { recordAiCall } from '../../../utils/metrics'
import { syncTopicToDisk, ensureTopicDir } from '../../../utils/topicStorage'
import { getAgentBaseUrl, requireOwnedChat } from '../../../utils/chatAccess'
import { callChatWithPersistentFallback, shouldUsePersistentMemory } from '../../../utils/agentInternalClient'
import { compactAfterSuccessfulAssistantPersistence } from '../../../utils/postTurnCompaction'
import { buildPersistentMemoryContext } from '../../../utils/persistentMemoryContext'
import {
  appendMessage,
  createAssistantMessageId,
  createAssistantStreamState,
  createCurrentMessageHandoff,
  persistCurrentUserMessage,
  shouldPersistAssistantMessage
} from '../../../utils/messageLifecycle'

const uiMessageSchema = z.object({
  id: z.string().min(1),
  parts: z.array(z.unknown()),
  role: z.enum(['user', 'assistant', 'system'])
}).passthrough()

export default defineHandler(async (event) => {
  const { id } = await getValidatedRouterParams(event, z.object({
    id: z.string()
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
    where: (chat, { eq }) => eq(chat.id, id as string),
    with: {
      messages: {
        orderBy: (message, { asc }) => asc(message.sequence)
      }
    }
  })
  if (!chat) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Chat not found' })
  }


  const lastMessage = messages[messages.length - 1]
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
  let shouldAttemptCompaction = false
  event.runtime?.node?.req?.on('close', () => {
    assistantState.clientAborted = true
    abortController.abort()
  })

  const stream = createUIMessageStream({
    onError: (err: any) => {
      assistantState.streamFailed = true
      console.error('[web-stream] onError occurred:', err)
      return 'Request failed.'
    },
    execute: async ({ writer }) => {
      try {
        console.log("[DEBUG queryText]", queryText)

        // Fetch Topic Space context if chat is linked to a topic
        let topicInfo: any = null
        let topicDocIds: string[] = []
        let topicTitles: string[] = []
        if (chat.topicId) {
          topicInfo = await db.query.topics.findFirst({
            where: eq(tables.topics.id, chat.topicId)
          })
          if (topicInfo) {
            const topicDocs = await db.query.topicDocuments.findMany({
              where: and(
                eq(tables.topicDocuments.topicId, topicInfo.id),
                eq(tables.topicDocuments.isRemoved, false)
              )
            })
            topicDocIds = topicDocs.map(d => d.docId)
            topicTitles = topicDocs.map(d => d.title)
          }
        }

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

        const usePersistentMemory = shouldUsePersistentMemory(actor.isAuthenticated)
        const memoryContext = usePersistentMemory
          ? await buildPersistentMemoryContext(db, currentAgentInput)
          : undefined
        const { soul_content: _soulContent, ...internalAgentFields } = publicAgentRequest
        const agentResult = await callChatWithPersistentFallback({
          usePersistentMemory,
          internalRequest: {
            ...internalAgentFields,
            memory_context: memoryContext!
          },
          callPublic: callPublicAgent,
          options: { signal: abortController.signal }
        })
        shouldAttemptCompaction = usePersistentMemory && 'response' in agentResult
        const agentData = 'response' in agentResult ? agentResult.response : agentResult
        recordAiCall(Date.now() - aiCallStart)

        if (agentData.chat_title) {
          await db.update(tables.chats).set({ title: agentData.chat_title }).where(eq(tables.chats.id, id as string))
          writer.write({
            type: 'data-chat-title',
            data: { title: agentData.chat_title }
          })
        }

        const isValidResponse = agentData.status === "success" || agentData.status === "clarification_required"
        if (!isValidResponse) {
          assistantState.streamFailed = true
          writer.write({
            type: 'error',
            errorText: 'Agent request failed.'
          })
          return
        }

        const rawAnswer = agentData.answer || agentData.message || ""
        const citationsList: any[] = agentData.citations || []
        assistantState.agentSucceeded = true
        const currentAssistantMessageId = createAssistantMessageId()
        assistantMessageId = currentAssistantMessageId

        // If chat belongs to a topic, accumulate citations into topic_documents pool & update anti-echo-chamber counter
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

              const latestTopic = await db.query.topics.findFirst({ where: eq(tables.topics.id, chat.topicId) })
              const latestDocs = await db.query.topicDocuments.findMany({ where: eq(tables.topicDocuments.topicId, chat.topicId) })
              if (latestTopic) {
                syncTopicToDisk(latestTopic.id, latestTopic, latestTopic.soulContent, latestDocs)
              }
            }
          } catch (docErr) {
            console.error('[TopicDocPoolUpdateError]', docErr)
          }
        }


        // 2. Replace [N] markers with :cite-mark{index="N"} — only pass index.
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

      } catch (err: any) {
        assistantState.streamFailed = true
        console.error('[web-post] error in agent call:', err)
        if (abortController.signal.aborted) {
          assistantState.clientAborted = true
          return
        }

        try {
          writer.write({
            type: 'error',
            errorText: 'Failed to retrieve an answer from the Agent layer.'
          })
        } catch (writerError) {
          console.error('[web-post] unable to write stream error:', writerError)
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
        await appendMessage(db, {
          id: assistantMessageId,
          chatId: chat.id,
          parts: [{ type: 'text', text: assistantState.assistantContent }],
          role: 'assistant'
        })
        if (shouldAttemptCompaction) {
          try {
            await compactAfterSuccessfulAssistantPersistence(db, currentAgentInput)
          } catch {
            // Snapshot planning is best-effort and must never affect this answer.
            console.error('[web-onFinish] post-turn compaction failed')
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
