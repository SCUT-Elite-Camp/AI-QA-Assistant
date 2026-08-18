<script setup lang="ts">
import { computed } from 'vue'
import type { UIMessage } from 'ai'
import { isToolUIPart, isTextUIPart, getToolName } from 'ai'
import { isToolStreaming } from '@nuxt/ui/utils/ai'

const props = defineProps<{
  status?: string
  lastMessage?: UIMessage
}>()

/**
 * Real backend system status derived directly from actual SSE message parts
 */
const realStatusText = computed(() => {
  if (!props.lastMessage || props.lastMessage.role !== 'assistant') {
    return '理解中...'
  }

  const parts = props.lastMessage.parts ?? []
  if (!parts.length) {
    return '理解中...'
  }

  let isSearching = false
  let retrievedCount = 0
  let hasText = false

  for (const part of parts) {
    if (isToolUIPart(part) && (getToolName(part) === 'rag_search' || getToolName(part) === 'search')) {
      if (isToolStreaming(part)) {
        isSearching = true
      }
      const output = (part as any).output || (part as any).result
      if (Array.isArray(output)) {
        retrievedCount = output.length
      }
    } else if (isTextUIPart(part) && (part as any).text?.trim()) {
      hasText = true
    }
  }

  if (hasText) {
    return '生成中...'
  }
  if (isSearching) {
    return '检索中...'
  }
  if (retrievedCount > 0) {
    return `已检索到 ${retrievedCount} 个切块，生成中...`
  }

  return '理解中...'
})
</script>

<template>
  <div class="py-1.5 flex items-center gap-2 text-xs text-zinc-300 font-sans select-none">
    <span class="w-1.5 h-1.5 rounded-full bg-zinc-400 animate-pulse shrink-0"></span>
    <span class="font-normal text-zinc-300">{{ realStatusText }}</span>
  </div>
</template>
