<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import type { UIMessage } from 'ai'
import { isToolUIPart, isTextUIPart, getToolName } from 'ai'

const props = defineProps<{
  status?: string
  messages?: UIMessage[]
}>()

const startTime = ref<number>(Date.now())
const elapsedSeconds = ref<number>(0)
let timer: ReturnType<typeof setInterval> | null = null

// Reset timer whenever streaming starts
watch(() => props.status, (newStatus) => {
  if (newStatus === 'streaming' || newStatus === 'submitted') {
    startTime.value = Date.now()
    elapsedSeconds.value = 0
    if (!timer) {
      timer = setInterval(() => {
        elapsedSeconds.value = (Date.now() - startTime.value) / 1000
      }, 300)
    }
  } else {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }
}, { immediate: true })

onUnmounted(() => {
  if (timer) clearInterval(timer)
})

/**
 * Real backend system status derived from AI SDK streaming events and elapsed time
 */
const realStatusText = computed(() => {
  const msgs = props.messages ?? []
  const assistantMsg = [...msgs].reverse().find(m => m.role === 'assistant')

  let isSearching = false
  let retrievedCount = 0
  let hasText = false

  if (assistantMsg?.parts) {
    for (const part of assistantMsg.parts) {
      if (isToolUIPart(part) && (getToolName(part) === 'rag_search' || getToolName(part) === 'search')) {
        isSearching = true
        const output = (part as any).output || (part as any).result
        if (Array.isArray(output) && output.length > 0) {
          retrievedCount = output.length
        }
      } else if (isTextUIPart(part) && (part as any).text?.trim()) {
        hasText = true
      }
    }
  }

  // 1. If text generation has started
  if (hasText) {
    return '回答生成中...'
  }

  // 2. If tool citations output has arrived
  if (retrievedCount > 0) {
    return `已检索到 ${retrievedCount} 个切块，生成中...`
  }

  // 3. If tool search is active or past 2s
  if (isSearching || elapsedSeconds.value >= 2.0) {
    return '知识库检索中...'
  }

  // 4. Initial phase
  return '意图理解中...'
})
</script>

<template>
  <div class="py-1.5 flex items-center gap-2 text-xs text-zinc-300 font-sans select-none">
    <span class="w-1.5 h-1.5 rounded-full bg-zinc-400 animate-pulse shrink-0"></span>
    <span class="font-normal text-zinc-300">{{ realStatusText }}</span>
  </div>
</template>
