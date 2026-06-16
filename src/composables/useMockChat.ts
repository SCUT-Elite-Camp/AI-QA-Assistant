import { ref, shallowRef } from 'vue'
import type { UIMessage } from 'ai'
import { createMockUserMessage, createMockAssistantMessage, mockSendChatMessageStream } from '../mock/mockAgent'
import { getErrorMessage } from '../mock/errorMap'

function getTextFromParts(parts: UIMessage['parts']): string {
  for (const part of parts) {
    if (part.type === 'text' && 'text' in part) {
      return (part as { text: string }).text
    }
  }
  return ''
}

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

    const userMsg = createMockUserMessage(params.text)
    const assistantMsg = createMockAssistantMessage()
    messages.value = [...messages.value, userMsg, assistantMsg]

    status.value = 'streaming'

    await mockSendChatMessageStream(
      { query: params.text },
      // onDelta
      (chunk: string) => {
        const msgs = messages.value
        const lastIdx = msgs.length - 1
        if (lastIdx >= 0 && msgs[lastIdx]!.role === 'assistant') {
          const current = msgs[lastIdx]!
          const currentText = getTextFromParts(current.parts || [])
          const newText = currentText + chunk
          messages.value = [
            ...msgs.slice(0, lastIdx),
            {
              ...current,
              parts: [{ type: 'text' as const, text: newText }],
            },
          ]
        }
      },
      // onDone
      (finalMsg: UIMessage) => {
        const msgs = messages.value
        const lastIdx = msgs.length - 1
        if (lastIdx >= 0 && msgs[lastIdx]!.role === 'assistant') {
          const accumulatedText = getTextFromParts(msgs[lastIdx]!.parts || [])
          const finalText = accumulatedText || getTextFromParts(finalMsg.parts || [])
          messages.value = [
            ...msgs.slice(0, lastIdx),
            {
              ...finalMsg,
              parts: [{ type: 'text' as const, text: finalText }],
            },
          ]
        }
        status.value = 'ready'
      },
      // onError
      (err: Error & { status?: string }) => {
        const msgs = messages.value
        const lastIdx = msgs.length - 1
        const errorText = getErrorMessage(err.status, err.message)
        if (lastIdx >= 0 && msgs[lastIdx]!.role === 'assistant') {
          messages.value = [
            ...msgs.slice(0, lastIdx),
            {
              ...msgs[lastIdx]!,
              parts: [{ type: 'text' as const, text: errorText }],
            },
          ]
        }
        status.value = 'error'
        error.value = err
      },
    )
  }

  async function regenerate(options?: { messageId?: string }) {
    error.value = undefined
    const msgs = messages.value
    const targetId = options?.messageId

    let targetIndex = -1
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (targetId) {
        if (msgs[i]!.id === targetId) {
          for (let j = i - 1; j >= 0; j--) {
            if (msgs[j]!.role === 'user') { targetIndex = j; break }
          }
          break
        }
      } else if (msgs[i]!.role === 'user') {
        targetIndex = i
        break
      }
    }

    if (targetIndex === -1) return

    const text = getTextFromParts(msgs[targetIndex]!.parts || [])
    messages.value = msgs.slice(0, targetIndex)

    if (text) {
      sendMessage({ text })
    }
  }

  function stop() {
    status.value = 'ready'
    error.value = undefined
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
