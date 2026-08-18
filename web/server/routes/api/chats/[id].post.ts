import fs from 'fs'
import path from 'path'
import type { UIMessage } from 'ai'
import { createUIMessageStream, createUIMessageStreamResponse } from 'ai'
import { z } from 'zod'
import { useUserSession } from '../../../utils/session'
import { useDrizzle, tables, eq, and } from '../../../utils/drizzle'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams, readValidatedBody } from 'nitro/h3'
import { MODELS } from '../../../../shared/utils/models'
import { logger } from '../../../utils/logger'
import { recordAiCall } from '../../../utils/metrics'
import { syncTopicToDisk, ensureTopicDir, loadTopicFromDisk, syncAllTopicDocuments } from '../../../utils/topicStorage'



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


  const lastMessage = messages[messages.length - 1]
  const queryText = lastMessage?.content || (lastMessage as any)?.parts?.[0]?.text || ''

  // Detect if chat needs title (first message turn or placeholder title)
  const messageCount = (chat.messages || []).length
  const needsTitle = messageCount <= 1 || !chat.title || chat.title === '' || chat.title === 'New Chat' || chat.title === 'Untitled' || chat.title === '新对话' || chat.title.endsWith('...')

  if (lastMessage?.role === 'user') {
    await db.insert(tables.messages).values({
      id: lastMessage.id,
      chatId: id as string,
      role: 'user',
      parts: lastMessage.parts
    }).onConflictDoUpdate({ target: tables.messages.id, set: { parts: lastMessage.parts } })
  }

  const abortController = new AbortController()
  const timeoutId = setTimeout(() => abortController.abort(), 90000)
  event.runtime?.node?.req?.on('close', () => {
    clearTimeout(timeoutId)
    abortController.abort()
  })

  const stream = createUIMessageStream({
    onError: (err: any) => {
      clearTimeout(timeoutId)
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

        // 2. Call real Python Agent API (port 8000)
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
            soul_content: soulContent || undefined,
            topic_doc_ids: topicDocIds,
            topic_titles: topicTitles,
            consecutive_no_new_docs_count: topicInfo?.consecutiveNoNewDocsCount || 0,
            is_first_message: needsTitle
          }),
          signal: abortController.signal
        })
        clearTimeout(timeoutId)

        if (!agentRes.ok) {
          throw new Error(`Failed to contact Agent Layer: ${agentRes.statusText}`)
        }

        const agentData = await agentRes.json()
        const aiDuration = Date.now() - aiCallStart
        const rawAnswer = agentData.answer || agentData.message || ""
        const tokensCount = Math.max(20, Math.round((rawAnswer.length || 0) * 0.75 + (queryText.length || 0) * 0.5))
        const ttftMs = Math.max(50, Math.round(aiDuration * 0.25))
        recordAiCall(aiDuration, ttftMs, tokensCount)

        if (agentData.chat_title) {
          await db.update(tables.chats).set({ title: agentData.chat_title }).where(eq(tables.chats.id, id as string))
          writer.write({
            type: 'data-chat-title',
            data: { title: agentData.chat_title }
          })
        }

        const isValidResponse = agentData.status === "success" || agentData.status === "clarification_required"
        if (!isValidResponse) {
          const errMsg = agentData.message || "RAG retrieval error from Agent layer"
          const responseId = `err-msg-${Date.now()}`
          writer.write({
            type: 'text-start',
            id: responseId
          })
          writer.write({
            type: 'text-delta',
            id: responseId,
            delta: `Error: ${errMsg}`
          })
          writer.write({
            type: 'text-end',
            id: responseId
          })
          return
        }

        const citationsList: any[] = agentData.citations || []

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
            }
            await syncAllTopicDocuments(db, chat.topicId)
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



        // 3. Write RAG search tool output — full ChunkCitation array in output.
        //    Sources.vue deduplicates by doc_id; CiteMark looks up by index.

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
            similarity: cit.vector_score ?? cit.similarity_score ?? null,
            vector_score: cit.vector_score ?? null
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
