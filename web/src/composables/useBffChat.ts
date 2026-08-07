import { ref, shallowRef } from 'vue'
import type { UIMessage } from 'ai'
import { $fetch } from 'ofetch'
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

/**
 * BFF chat composable that connects to the backend Agent via POST /api/chat/stream.
 * Mirrors the same API surface as useMockChat for drop-in replacement.
 */
export function useBffChat(options: BffChatOptions = {}) {
  const _messages = shallowRef<UIMessage[]>(options.messages || [])
  const _status = ref<'ready' | 'submitted' | 'streaming' | 'error'>('ready')
  const _error = ref<Error | undefined>(undefined)
  const _abortController = shallowRef<AbortController | null>(null)

  async function generateResponse(query: string) {
    _error.value = undefined
    _status.value = 'submitted'

    const assistantMsg: UIMessage = {
      id: `msg-${Date.now().toString(36)}-${Math.random().toString(16).slice(2, 8)}`,
      role: 'assistant',
      parts: [],
    } as unknown as UIMessage

    _messages.value = [..._messages.value, assistantMsg]
    _status.value = 'streaming'

    const controller = new AbortController()
    _abortController.value = controller

    try {
      const response = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          ...(options.id ? { session_id: options.id } : {})
        }),
        signal: controller.signal,
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        const status = errorData.status || 'network_error'
        const err = new Error(getErrorMessage(status, errorData.message)) as Error & { status?: string }
        err.status = status
        throw err
      }

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error('Response body is not readable')
      }

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.trim()) continue
          if (!line.startsWith('data:')) continue

          const dataStr = line.slice(5).trim()
          if (dataStr === '[DONE]') {
            _status.value = 'ready'
            _abortController.value = null
            return
          }

          try {
            const data = JSON.parse(dataStr)
            if (data.type === 'text-delta' && data.text) {
              const msgs = _messages.value
              const lastIdx = msgs.length - 1
              if (lastIdx >= 0 && msgs[lastIdx]!.role === 'assistant') {
                const current = msgs[lastIdx]!
                const currentText = getTextFromParts(current.parts || [])
                const newText = currentText + data.text
                _messages.value = [
                  ...msgs.slice(0, lastIdx),
                  {
                    ...current,
                    parts: [{ type: 'text' as const, text: newText }],
                  },
                ]
              }
            }
            if (data.type === 'error') {
              const err = new Error(getErrorMessage(data.status, data.message)) as Error & { status?: string }
              err.status = data.status
              throw err
            }
          } catch (parseErr) {
            // Ignore parse errors for non-JSON lines
            if (parseErr instanceof Error && 'status' in parseErr) throw parseErr
          }
        }
      }

      _status.value = 'ready'
      _abortController.value = null
    } catch (err) {
      const error = err as Error & { status?: string }
      if (error.name === 'AbortError') {
        _status.value = 'ready'
        _abortController.value = null
        return
      }

      const msgs = _messages.value
      const lastIdx = msgs.length - 1
      const errorText = getErrorMessage(error.status, error.message)
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
      _error.value = error
      _abortController.value = null
    }
  }

  async function sendMessage(params: { text: string; messageId?: string }) {
    if (_status.value === 'streaming') return

    const userMsg: UIMessage = {
      id: params.messageId || `msg-${Date.now().toString(36)}-${Math.random().toString(16).slice(2, 8)}`,
      role: 'user',
      parts: [{ type: 'text' as const, text: params.text }],
    } as unknown as UIMessage

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
    _messages.value = msgs.slice(0, targetIndex + 1)

    if (text) {
      await generateResponse(text)
    }
  }

  function stop() {
    if (_abortController.value) {
      _abortController.value.abort()
    }
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
