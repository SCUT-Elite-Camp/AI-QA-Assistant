import type { UIMessage } from 'ai'
import { createUIMessageStream, createUIMessageStreamResponse } from 'ai'
import { z } from 'zod'
import { defineHandler } from 'nitro'
import { readValidatedBody } from 'nitro/h3'
import { useUserSession } from '../../../utils/session'
import { useDrizzle, tables, eq, and } from '../../../utils/drizzle'
import { logger } from '../../../utils/logger'
import { recordAiCall } from '../../../utils/metrics'

export default defineHandler(async (event) => {
  const session = await useUserSession(event)
  const db = useDrizzle()

  // Accept standard AI SDK body format: messages array + extra context fields
  const body = await readValidatedBody(event, z.object({
    messages: z.array(z.custom<UIMessage>()),
    selectedText: z.string().optional(),
    contextText: z.string().optional(),
    topicId: z.string().optional(),
  }).parse)

  const { messages, selectedText, contextText, topicId } = body

  // Get last user message as the query
  const lastUserMsg = [...messages].reverse().find(m => m.role === 'user')
  const cleanQuery = lastUserMsg
    ? lastUserMsg.parts
        ?.filter((p: any) => p.type === 'text')
        ?.map((p: any) => p.text)
        ?.join('') || ''
    : ''

  const cleanSelected = (selectedText || '').trim()
  const cleanContext = (contextText || '').trim()

  // Build query: clearly emphasize the selected text is the TOPIC OF FOCUS.
  // The context is background only — Agent must answer about cleanSelected, not other topics in the passage.
  let queryText = ''
  if (cleanSelected && cleanQuery) {
    queryText = `用户在阅读一段文字时，划选了其中的关键词「${cleanSelected}」，并就此提问：${cleanQuery}

【重要】请重点围绕划选内容「${cleanSelected}」来回答，不要回答上下文中其他不相关的内容。`
    if (cleanContext) {
      queryText += `\n\n划选词所在的原文段落（仅供参考，回答核心仍是「${cleanSelected}」）：\n${cleanContext.slice(0, 800)}`
    }
  } else if (cleanSelected) {
    queryText = `用户划选了「${cleanSelected}」，请围绕此内容进行介绍和说明。`
    if (cleanContext) {
      queryText += `\n\n所在原文：\n${cleanContext.slice(0, 800)}`
    }
  } else {
    queryText = cleanQuery
  }

  // Include prior conversation history for multi-turn context
  const historyMessages: any[] = []
  for (const msg of messages.slice(0, -1)) {
    // skip non-user/assistant
    if (msg.role !== 'user' && msg.role !== 'assistant') continue
    const text = msg.parts
      ?.filter((p: any) => p.type === 'text')
      ?.map((p: any) => p.text)
      ?.join('') || ''
    if (text) {
      historyMessages.push({ role: msg.role, content: text })
    }
  }

  // Fetch Topic RAG info if topicId is provided
  let topicDocIds: string[] = []
  let topicInfo: any = null
  if (topicId) {
    topicInfo = await db.query.topics.findFirst({
      where: eq(tables.topics.id, topicId)
    })
    if (topicInfo) {
      const topicDocs = await db.query.topicDocuments.findMany({
        where: and(
          eq(tables.topicDocuments.topicId, topicInfo.id),
          eq(tables.topicDocuments.isRemoved, false)
        )
      })
      topicDocIds = topicDocs.map(d => d.docId)
    }
  }

  const abortController = new AbortController()
  event.runtime?.node?.req?.on('close', () => abortController.abort())

  const stream = createUIMessageStream({
    onError: (err: any) => {
      logger.error('[temp-ask] Error during stream:', err)
      return err.message || '服务异常，请稍后重试。'
    },
    execute: async ({ writer }) => {
      // 1. Send query directly to Python Agent layer (identical to standard chat)
      const agentUrl = "http://127.0.0.1:8000/api/chat"
      const aiCallStart = Date.now()
      let agentRes: Response
      try {
        agentRes = await fetch(agentUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            query: queryText,
            history: historyMessages,
            session_id: `temp_${Date.now()}`,
            top_k: 5,
            retrieval_mode: "hybrid",
            topic_id: topicId || undefined,
            weight_mode: topicInfo?.weightMode || "auto",
            soul_content: topicInfo?.soulContent || undefined,
            topic_doc_ids: topicDocIds,
            consecutive_no_new_docs_count: topicInfo?.consecutiveNoNewDocsCount || 0
          }),
          signal: abortController.signal
        })
      } catch (err: any) {
        logger.error("[temp-ask] Failed to reach Agent layer on port 8000:", err)
        throw new Error("Agent 后台服务连接异常，请稍后重试。")
      }

      if (!agentRes.ok) {
        throw new Error(`Agent层通信失败 (${agentRes.status})`)
      }

      const agentData = await agentRes.json()
      const aiDuration = Date.now() - aiCallStart
      const rawAnswer = agentData.answer || agentData.message || agentData.response || ""
      const tokensCount = Math.max(20, Math.round((rawAnswer.length || 0) * 0.75 + (queryText.length || 0) * 0.5))
      const ttftMs = Math.max(50, Math.round(aiDuration * 0.25))
      recordAiCall(aiDuration, ttftMs, tokensCount)
      const citationsList: any[] = agentData.citations || []

      // 2. Write rag_search tool result if citations returned from Agent
      if (citationsList.length > 0) {
        const toolCallId = `call_${Date.now()}`
        writer.write({
          type: 'tool-input-available',
          toolCallId,
          toolName: 'rag_search',
          input: { query: cleanQuery }
        } as any)

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
        } as any)
      }

      // 3. Replace [N] markers with :cite-mark{index="N"} for citation badges
      let processedAnswer = rawAnswer
      for (let i = 0; i < citationsList.length; i++) {
        const idx = i + 1
        processedAnswer = processedAnswer.split(`[${idx}]`).join(` :cite-mark{index="${idx}"}`)
      }

      // 4. Stream response text deltas to UI
      const responseId = `temp_resp_${Date.now()}`
      writer.write({ type: 'text-start', id: responseId })

      const chunkSize = 4
      for (let i = 0; i < processedAnswer.length; i += chunkSize) {
        const chunk = processedAnswer.slice(i, i + chunkSize)
        writer.write({
          type: 'text-delta',
          id: responseId,
          delta: chunk
        })
        await new Promise(resolve => setTimeout(resolve, 15))
      }

      writer.write({ type: 'text-end', id: responseId })
    }
  })

  return createUIMessageStreamResponse({ stream })
})
