import { ref, shallowRef } from 'vue'
import type { UIMessage } from 'ai'
import { createMockUserMessage, createMockAssistantMessage, mockSendChatMessageStream } from '../mock/mockAgent'
import { getErrorMessage } from '../mock/errorMap'

interface MockChatOptions {
  id?: string
  messages?: UIMessage[]
  isOwner?: boolean
}

export function useMockChat(options: MockChatOptions = {}) {
  const messages = shallowRef<UIMessage[]>(options.messages || [])
  const status = ref<'ready' | 'submitted' | 'streaming' | 'error'>('ready')
  const error = ref<Error | undefined>(undefined)

  async function sendMessage(params: { text: string; messageId?: string }) {
    if (status.value === 'streaming') return

    status.value = 'submitted'
    error.value = undefined

    // Add user message
    const userMsg = createMockUserMessage(params.text)
    const assistantMsg = createMockAssistantMessage()
    messages.value = [...messages.value, userMsg, assistantMsg]

    status.value = 'streaming'

    await mockSendChatMessageStream(
      { query: params.text },
      // onDelta - append text to assistant message
      (chunk: string) => {
        const msgs = messages.value
        const lastIdx = msgs.length - 1
        if (lastIdx >= 0 && msgs[lastIdx]!.role === 'assistant') {
          const current = msgs[lastIdx]!
          const newContent = (current.content || '') + chunk
          messages.value = [
            ...msgs.slice(0, lastIdx),
            {
              ...current,
              content: newContent,
              parts: [{ type: 'text' as const, text: newContent }],
            },
          ]
        }
      },
      // onDone - finalize assistant message
      (finalMsg: UIMessage) => {
        const msgs = messages.value
        const lastIdx = msgs.length - 1
        if (lastIdx >= 0 && msgs[lastIdx]!.role === 'assistant') {
          // Preserve accumulated streaming content if available, fallback to final message
          const accumulatedContent = msgs[lastIdx]!.content
          messages.value = [
            ...msgs.slice(0, lastIdx),
            {
              ...finalMsg,
              content: accumulatedContent || finalMsg.content,
            },
          ]
        }
        status.value = 'ready'
      },
      // onError
      (err: Error & { status?: string }) => {
        const msgs = messages.value
        const lastIdx = msgs.length - 1
        if (lastIdx >= 0 && msgs[lastIdx]!.role === 'assistant') {
          const errorText = getErrorMessage(err.status, err.message)
          messages.value = [
            ...msgs.slice(0, lastIdx),
            {
              ...msgs[lastIdx]!,
              content: errorText,
              parts: [{ type: 'text' as const, text: errorText }],
            },
          ]
        }
        status.value = 'error'
        error.value = err
      },
    )
  }

  function regenerate(options?: { messageId?: string }) {
    const msgs = messages.value
    const targetId = options?.messageId

    // Find the last user message
    let targetIndex = -1
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (targetId) {
        // Find the user message before the target message
        if (msgs[i]!.id === targetId) {
          // Look for the preceding user message
          for (let j = i - 1; j >= 0; j--) {
            if (msgs[j]!.role === 'user') {
              targetIndex = j
              break
            }
          }
          break
        }
      } else if (msgs[i]!.role === 'user') {
        targetIndex = i
        break
      }
    }

    if (targetIndex === -1) return

    const userMsg = msgs[targetIndex]!
    const text = userMsg.content || (userMsg.parts?.[0] && typeof userMsg.parts[0] === 'object' && 'text' in userMsg.parts[0] ? (userMsg.parts[0] as { text: string }).text : '')

    // Remove all messages from targetIndex onward
    messages.value = msgs.slice(0, targetIndex)

    if (text) {
      sendMessage({ text })
    }
  }

  function stop() {
    status.value = 'ready'
  }

  return {
    messages,
    status,
    error,
    sendMessage,
    regenerate,
    stop,
  }
}
