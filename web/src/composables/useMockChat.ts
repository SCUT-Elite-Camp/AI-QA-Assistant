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

/**
 * Mock chat that mirrors the Chat class API from @ai-sdk/vue.
 * Uses getter/setter properties like the Chat class so Vue templates
 * properly track reactivity and receive unwrapped values.
 */
export function useMockChat(options: MockChatOptions = {}) {
  // Internal refs – NOT exposed directly
  const _messages = shallowRef<UIMessage[]>(options.messages || [])
  const _status = ref<'ready' | 'submitted' | 'streaming' | 'error'>('ready')
  const _error = ref<Error | undefined>(undefined)

  // Core streaming helper: appends assistant message & streams response
  async function generateResponse(query: string) {
    _error.value = undefined
    _status.value = 'submitted'

    const assistantMsg = createMockAssistantMessage()
    _messages.value = [..._messages.value, assistantMsg]
    _status.value = 'streaming'

    await mockSendChatMessageStream(
      { query },
      // onDelta
      (chunk: string) => {
        const msgs = _messages.value
        const lastIdx = msgs.length - 1
        if (lastIdx >= 0 && msgs[lastIdx]!.role === 'assistant') {
          const current = msgs[lastIdx]!
          const currentText = getTextFromParts(current.parts || [])
          const newText = currentText + chunk
          _messages.value = [
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
        const msgs = _messages.value
        const lastIdx = msgs.length - 1
        if (lastIdx >= 0 && msgs[lastIdx]!.role === 'assistant') {
          const accumulatedText = getTextFromParts(msgs[lastIdx]!.parts || [])
          const finalText = accumulatedText || getTextFromParts(finalMsg.parts || [])
          _messages.value = [
            ...msgs.slice(0, lastIdx),
            {
              ...finalMsg,
              parts: [{ type: 'text' as const, text: finalText }],
            },
          ]
        }
        _status.value = 'ready'
      },
      // onError
      (err: Error & { status?: string }) => {
        const msgs = _messages.value
        const lastIdx = msgs.length - 1
        const errorText = getErrorMessage(err.status, err.message)
        if (lastIdx >= 0 && msgs[lastIdx]!.role === 'assistant') {
          _messages.value = [
            ...msgs.slice(0, lastIdx),
            {
              ...msgs[lastIdx]!,
              parts: [{ type: 'text' as const, text: errorText }],
            },
          ]
        }
        _status.value = 'error'
        _error.value = err
      },
    )
  }

  async function sendMessage(params: { text: string; messageId?: string }) {
    if (_status.value === 'streaming') return

    const userMsg = createMockUserMessage(params.text)
    _messages.value = [..._messages.value, userMsg]

    await generateResponse(params.text)
  }

  async function regenerate(options?: { messageId?: string }) {
    _error.value = undefined
    const msgs = _messages.value
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
    // Keep the user message, strip only assistant responses after it
    _messages.value = msgs.slice(0, targetIndex + 1)

    if (text) {
      await generateResponse(text)
    }
  }

  function stop() {
    _status.value = 'ready'
    _error.value = undefined
  }

  // Return object with getter/setter properties (matches Chat class API)
  // This is critical: Vue templates need getters that return raw values,
  // not Ref objects. The Chat class from @ai-sdk/vue does exactly this.
  return {
    get messages(): UIMessage[] { return _messages.value },
    set messages(v: UIMessage[]) { _messages.value = v },
    get status() { return _status.value },
    set status(v: 'ready' | 'submitted' | 'streaming' | 'error') { _status.value = v },
    get error() { return _error.value },
    set error(v: Error | undefined) { _error.value = v },
    sendMessage,
    regenerate,
    stop,
  }
}
