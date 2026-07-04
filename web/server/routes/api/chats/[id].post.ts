import type { UIMessage } from 'ai'
import { createUIMessageStream, createUIMessageStreamResponse } from 'ai'
import { z } from 'zod'
import { useUserSession } from '../../../utils/session'
import { useDrizzle, tables, eq, and } from '../../../utils/drizzle'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams, readValidatedBody } from 'nitro/h3'
import { MODELS } from '../../../../shared/utils/models'

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
        const queryText = lastMessage?.content || (lastMessage as any)?.parts?.[0]?.text || ''
        console.log("[DEBUG queryText]", queryText)
        
        // Write a transient status so the user knows RAG is searching
        if (!chat.title) {
          writer.write({
            type: 'data-chat-title',
            data: { message: 'Generating title...' },
            transient: true
          })
        }

        // 1. Call real Python Agent API (port 8000)
        const agentUrl = "http://127.0.0.1:8000/api/chat"
        const agentRes = await fetch(agentUrl, {
          method: "POST",
          headers: { 
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            query: queryText,
            top_k: 5,
            retrieval_mode: "hybrid"
          }),
          signal: abortController.signal
        })

        if (!agentRes.ok) {
          throw new Error(`Failed to contact Agent Layer: ${agentRes.statusText}`)
        }

        const agentData = await agentRes.json()

        if (agentData.status !== "success") {
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

        const rawAnswer = agentData.answer || ""
        const citationsList = agentData.citations || []

        // 2. Format citations as inline markdown source-links for comark with proper spacing
        let processedAnswer = rawAnswer
        for (let i = 0; i < citationsList.length; i++) {
          const cit = citationsList[i]
          const index = i + 1
          const url = cit.source_url || `https://local-document/${cit.doc_id}`
          const label = cit.title || cit.doc_id || `Doc ${index}`
          const favicon = `https://www.google.com/s2/favicons?sz=32&domain=example.com`
          const replacement = `[${index}] :source-link{url="${url.replace(/"/g, '&quot;')}" favicon="${favicon}" label="${label.replace(/"/g, '&quot;')}"}`
          processedAnswer = processedAnswer.split(`[${index}]`).join(replacement)
        }

        // 3. Write search tool invocation & results to trigger the Sources UI component
        const toolCallId = `call_${Date.now()}`
        writer.write({
          type: 'tool-input-available',
          toolCallId,
          toolName: 'web_search',
          input: { query: queryText }
        })

        writer.write({
          type: 'tool-output-available',
          toolCallId,
          output: citationsList.map((cit: any, idx: number) => ({
            url: cit.source_url || `https://local-document/${cit.doc_id}`,
            title: cit.title || cit.doc_id || `Document ${idx + 1}`
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
