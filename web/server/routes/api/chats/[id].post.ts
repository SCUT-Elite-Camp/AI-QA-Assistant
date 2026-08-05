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

async function generateSmartTitle(userQuery: string): Promise<string> {
  const cleanQuery = userQuery.trim().replace(/^[\s\n\r]+/, '')
  if (!cleanQuery) return '新对话'

  try {
    const apiKey = process.env.LLM_API_KEY || 'ak_2tl4PD6KT2Yu9Sf67W02t2S09GD6C'
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

  const { model, messages } = await readValidatedBody(event, z.object({
    model: z.string().refine(value => MODELS.some(m => m.value === value), {
      message: 'Invalid model'
    }),
    messages: z.array(z.custom<UIMessage>())
  }).parse)

  const db = useDrizzle()

  const chat = await db.query.chats.findFirst({
    where: (chat, { eq }) => and(eq(chat.id, id as string), eq(chat.userId, session.data.user?.id || session.id!)),
    with: {
      messages: true
    }
  })
  if (!chat) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Chat not found' })
  }

  const lastMessage = messages[messages.length - 1]
  const queryText = lastMessage?.content || (lastMessage as any)?.parts?.[0]?.text || ''

  // Generate smart title from user content during first conversation turn
  const needsTitle = !chat.title || chat.title === '' || chat.title === 'New Chat' || chat.title === 'Untitled' || chat.title === '新对话'
  let newTitle = ''
  if (needsTitle && queryText) {
    newTitle = await generateSmartTitle(queryText)
    await db.update(tables.chats).set({ title: newTitle }).where(eq(tables.chats.id, id as string))
  }

  if (lastMessage?.role === 'user' && messages.length > 1) {
    await db.insert(tables.messages).values({
      id: lastMessage.id,
      chatId: id as string,
      role: 'user',
      parts: lastMessage.parts
    }).onConflictDoUpdate({ target: tables.messages.id, set: { parts: lastMessage.parts } })
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
        
        if (newTitle) {
          writer.write({
            type: 'data-chat-title',
            data: { title: newTitle }
          })
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
            retrieval_mode: "hybrid"
          }),
          signal: abortController.signal
        })

        if (!agentRes.ok) {
          throw new Error(`Failed to contact Agent Layer: ${agentRes.statusText}`)
        }

        const agentData = await agentRes.json()
        recordAiCall(Date.now() - aiCallStart)

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

        const rawAnswer = agentData.answer || agentData.message || ""
        const citationsList: any[] = agentData.citations || []

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
        writer.write({
          type: 'text-start',
          id: responseId
        })
        writer.write({
          type: 'text-delta',
          id: responseId,
          delta: `Failed to retrieve answer from Agent Layer: ${err.message}`
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
