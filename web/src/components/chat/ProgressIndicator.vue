<script setup lang="ts">
import { computed } from 'vue'
import type { UIMessage } from 'ai'
import { isToolUIPart, isTextUIPart, getToolName } from 'ai'
import { isToolStreaming } from '@nuxt/ui/utils/ai'

const props = defineProps<{
  status?: string
  messages?: UIMessage[]
}>()

/**
 * 100% Real backend system status derived strictly from actual SSE message parts (NO timers/estimations)
 */
const realStatusText = computed(() => {
  const msgs = props.messages ?? []
  const assistantMsg = [...msgs].reverse().find(m => m.role === 'assistant')

  if (!assistantMsg || !assistantMsg.parts || !assistantMsg.parts.length) {
    return '意图理解中...'
  }

  let isToolExecuting = false
  let retrievedCount = 0
  let hasTextContent = false

  for (const part of assistantMsg.parts) {
    if (isToolUIPart(part) && (getToolName(part) === 'rag_search' || getToolName(part) === 'search')) {
      if (isToolStreaming(part)) {
        isToolExecuting = true
      }
      const output = (part as any).output || (part as any).result
      if (Array.isArray(output) && output.length > 0) {
        retrievedCount = output.length
      }
    } else if (isTextUIPart(part) && (part as any).text?.trim()) {
      hasTextContent = true
    }
  }

  if (hasTextContent) {
    return '回答生成中...'
  }

  if (retrievedCount > 0) {
    return `已检索到 ${retrievedCount} 个切块，生成中...`
  }

  if (isToolExecuting) {
    return '知识库检索中...'
  }

  return '意图理解中...'
})
</script>

<template>
  <div class="py-1.5 flex items-center gap-2 text-xs text-zinc-300 font-sans select-none">
    <span class="w-1.5 h-1.5 rounded-full bg-zinc-400 animate-pulse shrink-0"></span>
    <span class="font-normal text-zinc-300">{{ realStatusText }}</span>
  </div>
</template>
