import { ref, shallowRef } from 'vue'
import type { UIMessage } from 'ai'
import { createUserMessage, sendChatMessage } from '../api/agentApi'
import { getErrorMessage } from '../mock/errorMap'

function getTextFromParts(parts: UIMessage['parts']): string {
  for (const part of parts) {
    if (part.type === 'text' && 'text' in part) {
      return (part as { text: string }).text
    }
  }
  return ''
}

interface BffChatOptions {
  id?: string
  messages?: UIMessage[]
}

export function useBffChat(options: BffChatOptions = {}) {
  const _messages = shallowRef<UIMessage[]>(options.messages || [])
  const _status = ref<'ready' | 'submitted' | 'streaming' | 'error'>('ready')
  const _error = ref<Error | undefined>(undefined)

  async function generateResponse(query: string) {
    _error.value = undefined
    _status.value = 'submitted'

    try {
      const assistantMessage = await sendChatMessage(query, {
        sessionId: options.id || 'local-session-001',
        stream: false,
      })
      _messages.value = [..._messages.value, assistantMessage]
      _status.value = 'ready'
    } catch (err) {
      const error = err as Error & { status?: string }
      const errorText = getErrorMessage(error.status, error.message)
      _messages.value = [
        ..._messages.value,
        {
          id: `error-${Date.now().toString(36)}`,
          role: 'assistant',
          parts: [{ type: 'text' as const, text: errorText }],
        } as unknown as UIMessage,
      ]
      _status.value = 'error'
      _error.value = error
    }
  }

  async function sendMessage(params: { text: string; messageId?: string }) {
    if (_status.value === 'submitted' || _status.value === 'streaming') return

    _messages.value = [..._messages.value, createUserMessage(params.text)]
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
    _messages.value = msgs.slice(0, targetIndex + 1)

    if (text) {
      await generateResponse(text)
    }
  }

  function stop() {
    _status.value = 'ready'
    _error.value = undefined
  }

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
