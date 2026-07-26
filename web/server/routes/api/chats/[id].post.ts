import type { UIMessage } from 'ai'
import { convertToModelMessages, createUIMessageStream, createUIMessageStreamResponse, generateText, smoothStream, stepCountIs, streamText } from 'ai'
import { gateway } from '@ai-sdk/gateway'
import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams } from 'nitro/h3'
import type { AnthropicLanguageModelOptions } from '@ai-sdk/anthropic'
import { anthropic } from '@ai-sdk/anthropic'
import type { GoogleLanguageModelOptions } from '@ai-sdk/google'
// import { google } from '@ai-sdk/google'
import type { OpenAILanguageModelResponsesOptions } from '@ai-sdk/openai'
import { openai } from '@ai-sdk/openai'
import { useUserSession } from '../../../utils/session'
import { useDrizzle, tables, eq, and } from '../../../utils/drizzle'
import { weatherTool } from '../../../utils/tools/weather'
import { chartTool } from '../../../utils/tools/chart'
import { MODELS } from '../../../../shared/utils/models'
import { logger } from '../../../utils/logger'
import { recordAiCall } from '../../../utils/metrics'

export default defineHandler(async (event) => {
  const session = await useUserSession(event)
  const traceId = (event as any).__traceId || 'unknown'

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

  if (!chat.title) {
    const titleStart = Date.now()
    const { text: title } = await generateText({
      model: gateway('openai/gpt-4.1-nano'),
      system: `You are a title generator for a chat:
          - Generate a short title based on the first user's message
          - The title should be less than 30 characters long
          - The title should be a summary of the user's message
          - Do not use quotes (' or ") or colons (:) or any other punctuation
          - Do not use markdown, just plain text`,
      prompt: JSON.stringify(messages[0])
    })
    logger.debug({ traceId, chatId: id, titleGenMs: Date.now() - titleStart, title }, 'title generated')

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
    execute: async ({ writer }) => {
      const aiStart = Date.now()
      let firstTokenTime: number | null = null
      let totalTokens = 0

      const result = streamText({
        abortSignal: abortController.signal,
        model: gateway(model),
        system: `You are a knowledgeable and helpful AI assistant. ${session.data.user?.username ? `The user's name is ${session.data.user.username}.` : ''} Your goal is to provide clear, accurate, and well-structured responses.

**FORMATTING RULES (CRITICAL):**
- ABSOLUTELY NO MARKDOWN HEADINGS: Never use #, ##, ###, ####, #####, or ######
- NO underline-style headings with === or ---
- Use **bold text** for emphasis and section labels instead
- Examples:
  * Instead of "## Usage", write "**Usage:**" or just "Here's how to use it:"
  * Instead of "# Complete Guide", write "**Complete Guide**" or start directly with content
- Start all responses with content, never with a heading

**WEB SEARCH:**
- You have access to a web search tool to find current, up-to-date information
- Only use it when the user explicitly asks about recent events, real-time data, or current facts
- Do NOT search proactively — rely on your knowledge first
- Cite your sources when providing information from web search results

**RESPONSE QUALITY:**
- Be concise yet comprehensive
- Use examples when helpful
- Break down complex topics into digestible parts
- Maintain a friendly, professional tone`,
        messages: await convertToModelMessages(messages),
        tools: {
          chart: chartTool,
          weather: weatherTool,
          ...(model.startsWith('anthropic/') && { web_search: anthropic.tools.webSearch_20250305() }),
          ...(model.startsWith('openai/') && { web_search: openai.tools.webSearch() })
        },
        providerOptions: {
          anthropic: {
            thinking: {
              type: 'enabled',
              budgetTokens: 2048
            }
          } satisfies AnthropicLanguageModelOptions,
          google: {
            thinkingConfig: {
              includeThoughts: true,
              thinkingLevel: 'low'
            }
          } satisfies GoogleLanguageModelOptions,
          openai: {
            reasoningEffort: 'low',
            reasoningSummary: 'detailed'
          } satisfies OpenAILanguageModelResponsesOptions
        },
        stopWhen: stepCountIs(5),
        experimental_transform: smoothStream()
      })

      // 监听流中的 token 来记录首 token 时间和总 token 数
      const originalMerge = writer.merge.bind(writer)
      writer.merge = (source: any) => {
        const reader = source.getReader?.()
        if (!reader) return originalMerge(source)

        const wrappedStream = new ReadableStream({
          async start(controller) {
            try {
              while (true) {
                const { done, value } = await reader.read()
                if (done) break
                // 记录首 token 时间
                if (!firstTokenTime) {
                  firstTokenTime = Date.now()
                  logger.debug({ traceId, chatId: id, model, ttftMs: firstTokenTime - aiStart }, 'first token received')
                }
                // 估算 token 数（粗略：每个 chunk 约 4 字符 ≈ 1 token）
                if (value?.data) {
                  try {
                    const text = typeof value.data === 'string' ? value.data : JSON.stringify(value.data)
                    totalTokens += Math.ceil(text.length / 4)
                  } catch { /* ignore */ }
                }
                controller.enqueue(value)
              }
              controller.close()
            } catch (err) {
              controller.error(err)
            }
          }
        })
        return originalMerge({ ...source, getReader: () => wrappedStream.getReader() })
      }

      if (!chat.title) {
        writer.write({
          type: 'data-chat-title',
          data: { message: 'Generating title...' },
          transient: true
        })
      }

      writer.merge(result.toUIMessageStream({
        sendSources: true,
        sendReasoning: true
      }))
    },
    onFinish: async ({ messages }) => {
      await db.insert(tables.messages).values(messages.map(message => ({
        id: message.id,
        chatId: chat.id,
        role: message.role as 'user' | 'assistant',
        parts: message.parts
      }))).onConflictDoNothing()
    }
  })

  // 在流响应中包装以记录总耗时
  const response = createUIMessageStreamResponse({ stream })

  // 记录 AI 调用 metrics
  const originalResponseBody = response.body
  if (originalResponseBody) {
    const reader = (originalResponseBody as ReadableStream).getReader()
    const aiStart = Date.now()
    let firstTokenTime: number | null = null
    let totalTokens = 0

    const monitoredStream = new ReadableStream({
      async start(controller) {
        try {
          while (true) {
            const { done, value } = await reader.read()
            if (done) {
              const totalDuration = Date.now() - aiStart
              const ttft = firstTokenTime ? firstTokenTime - aiStart : totalDuration
              recordAiCall(totalDuration, ttft, totalTokens)
              logger.info({
                traceId,
                chatId: id,
                model,
                totalDurationMs: totalDuration,
                ttftMs: ttft,
                estimatedTokens: totalTokens,
              }, 'ai call completed')
              controller.close()
              break
            }
            if (!firstTokenTime) {
              firstTokenTime = Date.now()
            }
            // 估算 token
            const text = new TextDecoder().decode(value)
            totalTokens += Math.ceil(text.length / 4)
            controller.enqueue(value)
          }
        } catch (err) {
          const totalDuration = Date.now() - aiStart
          const ttft = firstTokenTime ? firstTokenTime - aiStart : totalDuration
          recordAiCall(totalDuration, ttft, totalTokens)
          logger.error({ traceId, chatId: id, model, totalDurationMs: totalDuration, err }, 'ai call failed')
          controller.error(err)
        }
      }
    })

    return new Response(monitoredStream, {
      status: response.status,
      headers: response.headers,
    })
  }

  return response
})
