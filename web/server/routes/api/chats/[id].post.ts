import fs from 'fs'
import path from 'path'
import { createHmac } from 'node:crypto'
import type { UIMessage } from 'ai'
import { createUIMessageStream, createUIMessageStreamResponse } from 'ai'
import { z } from 'zod'
import { useUserSession } from '../../../utils/session'
import { useDrizzle, tables, eq, and, inArray } from '../../../utils/drizzle'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams, readValidatedBody } from 'nitro/h3'
import { MODELS } from '../../../../shared/utils/models'
import { logger } from '../../../utils/logger'
import { recordAiCall } from '../../../utils/metrics'
import { syncTopicToDisk, ensureTopicDir } from '../../../utils/topicStorage'
import { requireAttachmentAccess } from '../../../utils/attachmentAccess'
import { requireCsrf, requirePrincipal, requireTopicRole } from '../../../utils/attachmentAuth'
import { extractAttachmentSelection, mergeSafeAttachmentParts } from '../../../../shared/utils/attachmentParts'
import { canSelectAttachmentForChat } from '../../../../shared/utils/attachmentScope'
import { createAgentStreamError, getAgentFailureMessage } from '../../../utils/agentResponse'
import { getOrCreateDefaultLibrary } from '../../../utils/library'
import { knowledgeBaseRetrievalEnabled } from '../../../../shared/utils/chatRetrieval'



async function generateSmartTitle(userQuery: string): Promise<string> {
  const cleanQuery = userQuery.trim().replace(/^[\s\n\r]+/, '')
  if (!cleanQuery) return '新对话'

  try {
    const apiKey = process.env.LLM_API_KEY || ''
    const apiBase = process.env.LLM_API_BASE || 'https://api.longcat.chat/openai/v1'
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 4000)

    const res = await fetch(`${apiBase}/chat/completions`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        model: process.env.LLM_MODEL || 'LongCat-2.0',
        messages: [
          { role: 'system', content: '你是对话标题生成器。根据用户第一次提出的问题，总结生成一个简短、精炼的主题标题（15字以内，绝对不要包含标点符号、引号或多余文字）。' },
          { role: 'user', content: cleanQuery }
        ],
        max_tokens: 30,
        temperature: 0.3
      }),
      signal: controller.signal
    })
    clearTimeout(timeoutId)
    if (res.ok) {
      const data = await res.json()
      const title = data?.choices?.[0]?.message?.content?.trim()
        ?.replace(/['"“”`\.\!\?。！？]/g, '')
      if (title && title.length >= 2 && title.length <= 25) {
        return title
      }
    }
  } catch (e) {
    console.warn('[TitleGen] LLM title gen fallback:', e)
  }

  return cleanQuery.length > 20 ? cleanQuery.slice(0, 20) + '...' : cleanQuery
}

export default defineHandler(async (event) => {
  requireCsrf(event)
  const session = await useUserSession(event)

  const { id } = await getValidatedRouterParams(event, z.object({
    id: z.string()
  }).parse)

  const body = await readValidatedBody(event, z.object({
    model: z.string().optional(),
    messages: z.array(z.custom<UIMessage>())
  }).parse)

  const selectedModel = (body.model && MODELS.some(m => m.value === body.model)) ? body.model : MODELS[0].value
  const messages = body.messages

  const db = useDrizzle()

  const chat = await db.query.chats.findFirst({
    where: (chat, { eq }) => eq(chat.id, id as string),
    with: {
      messages: true
    }
  })
  if (!chat) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Chat not found' })
  }
  const principal = await requirePrincipal(event)
  const personalLibrary = await getOrCreateDefaultLibrary(principal)
  const librarySecret = process.env.ATTACHMENT_INTERNAL_SECRET || ''
  const personalLibraryContext = librarySecret ? {
    owner_user_id: principal,
    knowledge_base_id: personalLibrary.id,
    access_token: createHmac('sha256', librarySecret).update(`${principal}:${personalLibrary.id}`).digest('hex')
  } : undefined
  if (chat.topicId) await requireTopicRole(event, chat.topicId, 'viewer')
  else if (chat.userId !== principal) throw new HTTPError({ statusCode: 403, statusMessage: 'chat_forbidden' })


  const lastMessage = messages[messages.length - 1]
  const queryText = lastMessage?.content || (lastMessage as any)?.parts?.[0]?.text || ''
  const messageMetadata = (lastMessage as any)?.metadata || {}
  const useKnowledgeBase = knowledgeBaseRetrievalEnabled(
    messageMetadata,
    (lastMessage as any)?.parts,
  )
  const attachmentSelection = extractAttachmentSelection((lastMessage as any)?.parts, messageMetadata)
  const selectedAttachmentIds = attachmentSelection.attachmentIds
  for (const attachmentId of selectedAttachmentIds) await requireAttachmentAccess(event, attachmentId)
  const selectedAttachments = selectedAttachmentIds.length
    ? await db.query.attachments.findMany({ where: inArray(tables.attachments.id, selectedAttachmentIds) })
    : []
  if (selectedAttachments.some(item => !canSelectAttachmentForChat(item, chat.id, chat.topicId))) {
    throw new HTTPError({ statusCode: 409, statusMessage: 'attachment_scope_mismatch' })
  }
  if (selectedAttachments.some(item => item.topicId && item.topicId !== chat.topicId)) {
    throw new HTTPError({ statusCode: 403, statusMessage: 'attachment_space_mismatch' })
  }
  const acceptedReviewIds = new Set(attachmentSelection.acceptedNeedsReviewIds)
  if (selectedAttachments.some(item => item.status !== 'ready' && !(item.status === 'needs_review' && acceptedReviewIds.has(item.id)))) {
    throw new HTTPError({ statusCode: 409, statusMessage: 'attachments_not_ready_or_unconfirmed' })
  }

  // Detect if chat needs title (first message turn or placeholder title)
  const messageCount = (chat.messages || []).length
  const needsTitle = messageCount <= 1 || !chat.title || chat.title === '' || chat.title === 'New Chat' || chat.title === 'Untitled' || chat.title === '新对话' || chat.title.endsWith('...')

  if (lastMessage?.role === 'user' && messages.length > 1) {
    const preferenceParts = [
      ...(Array.isArray(lastMessage.parts)
        ? lastMessage.parts.filter(part => part.type !== 'data-chat-preferences')
        : []),
      {
        type: 'data-chat-preferences',
        data: { knowledge_base_retrieval_enabled: useKnowledgeBase }
      }
    ]
    const safeParts = mergeSafeAttachmentParts(preferenceParts, selectedAttachments, acceptedReviewIds)
    await db.insert(tables.messages).values({
      id: lastMessage.id,
      chatId: id as string,
      role: 'user',
      parts: safeParts
    }).onConflictDoUpdate({ target: tables.messages.id, set: { parts: safeParts } })
    if (selectedAttachments.length) {
      await db.insert(tables.messageAttachments).values(selectedAttachments.map(item => ({
        messageId: lastMessage.id, attachmentId: item.id, evidenceVersion: item.evidenceVersion
      }))).onConflictDoNothing()
    }
  }

  const abortController = new AbortController()
  event.runtime?.node?.req?.on('close', () => abortController.abort())

  const stream = createUIMessageStream({
    onError: (err: any) => {
      console.error('[web-stream] onError occurred:', err)
      return err.message || 'An error occurred.'
    },
    execute: async ({ writer }) => {
      try {
        console.log("[DEBUG queryText]", queryText)

        // Fetch Topic Space context if chat is linked to a topic
        let topicInfo: any = null
        let topicDocIds: string[] = []
        let topicTitles: string[] = []
        let topicAttachmentIds: string[] = []
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
            const topicAttachments = await db.query.attachments.findMany({
              where: and(eq(tables.attachments.topicId, topicInfo.id), eq(tables.attachments.scope, 'topic'))
            })
            topicAttachmentIds = topicAttachments.filter(item => item.status === 'ready' && !item.deletedAt).map(item => item.id)
          }
        }

        // 1. Call real Python Agent API (port 8000)
        const agentUrl = "http://127.0.0.1:8000/api/chat"
        const aiCallStart = Date.now()
        const agentRes = await fetch(agentUrl, {
          method: "POST",
          headers: { 
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            query: queryText,
            session_id: id,
            top_k: 5,
            retrieval_mode: "hybrid",
            topic_id: chat.topicId || undefined,
            weight_mode: topicInfo?.weightMode || "auto",
            soul_content: topicInfo?.soulContent || undefined,
            topic_doc_ids: topicDocIds,
            topic_titles: topicTitles,
            consecutive_no_new_docs_count: topicInfo?.consecutiveNoNewDocsCount || 0,
            is_first_message: needsTitle,
            knowledge_base_retrieval_enabled: useKnowledgeBase
            ,personal_library_context: personalLibraryContext
            ,attachment_context: {
              selected_attachment_ids: selectedAttachmentIds,
              topic_attachment_ids: topicAttachmentIds,
              allowed_attachment_ids: Array.from(new Set([...selectedAttachmentIds, ...topicAttachmentIds]))
            }
          }),
          signal: abortController.signal
        })

        if (!agentRes.ok) {
          throw new Error(`Failed to contact Agent Layer: ${agentRes.statusText}`)
        }

        const agentData = await agentRes.json()
        recordAiCall(Date.now() - aiCallStart)

        if (agentData.chat_title) {
          await db.update(tables.chats).set({ title: agentData.chat_title }).where(eq(tables.chats.id, id as string))
          writer.write({
            type: 'data-chat-title',
            data: { title: agentData.chat_title }
          })
        }

        const agentFailure = getAgentFailureMessage(agentData)
        if (agentFailure) {
          writer.write(createAgentStreamError(agentFailure))
          return
        }

        const rawAnswer = agentData.answer || agentData.message || ""
        const citationsList: any[] = agentData.citations || []

        // If chat belongs to a topic, accumulate citations into topic_documents pool & update anti-echo-chamber counter
        if (chat.topicId && citationsList.length > 0) {
          try {
            let hasNewDocs = false
            for (const cit of citationsList.filter((item: any) => !['attachment', 'personal'].includes(item.source_type))) {
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
            source_type: cit.source_type || 'knowledge',
            attachment_id: cit.attachment_id || null,
            evidence_id: cit.evidence_id || null,
            locator: cit.locator || null,
            version: cit.version || null,
            source_scope: cit.source_scope || null,
            knowledge_base_id: cit.knowledge_base_id || null,
            document_id: cit.document_id || null,
            version_id: cit.version_id || null,
          }))
        })


        // 4. Stream answer text chunk-by-chunk to simulate real-time typing
        const responseId = `assistant-msg-${Date.now()}`
        writer.write({
          type: 'text-start',
          id: responseId
        })

        const chunkSize = 2
        for (let i = 0; i < processedAnswer.length; i += chunkSize) {
          const chunk = processedAnswer.slice(i, i + chunkSize)
          writer.write({
            type: 'text-delta',
            id: responseId,
            delta: chunk
          })
          // Small delay for natural streaming pacing
          await new Promise((resolve) => setTimeout(resolve, 20))
        }

        writer.write({
          type: 'text-end',
          id: responseId
        })

      } catch (err: any) {
        console.error('[web-post] error in agent call:', err)
        writer.write(createAgentStreamError(err))
      }
    },
    onFinish: async ({ messages }) => {
      try {
        await db.insert(tables.messages).values(messages.map(message => ({
          id: message.id,
          chatId: chat.id,
          role: message.role as 'user' | 'assistant',
          parts: message.parts
        }))).onConflictDoNothing()
      } catch (dbErr) {
        console.error('[web-onFinish] DB save error:', dbErr)
      }
    }
  })

  return createUIMessageStreamResponse({
    stream
  })
})
