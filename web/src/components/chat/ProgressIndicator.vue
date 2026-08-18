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
 * 100% Real backend system status derived strictly from current turn SSE message parts
 */
const realStatusText = computed(() => {
  const msgs = props.messages ?? []
  
  // Find index of the latest user message for the current turn
  let lastUserIdx = -1
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === 'user') {
      lastUserIdx = i
      break
    }
  }

  // Only inspect assistant message created AFTER the latest user message
  let currentAssistantMsg: UIMessage | undefined = undefined
  if (lastUserIdx !== -1) {
    for (let i = lastUserIdx + 1; i < msgs.length; i++) {
      if (msgs[i].role === 'assistant') {
        currentAssistantMsg = msgs[i]
        break
      }
    }
  }

  // If no assistant message has been created yet for this turn
  if (!currentAssistantMsg || !currentAssistantMsg.parts || !currentAssistantMsg.parts.length) {
    return '意图理解中...'
  }

  let isToolExecuting = false
  let retrievedCount = 0
  let hasTextContent = false

  for (const part of currentAssistantMsg.parts) {
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
  <div class="py-1.5 flex items-center gap-2 text-sm text-neutral-300 font-sans select-none">
    <span class="w-2 h-2 rounded-full bg-neutral-400 animate-pulse shrink-0"></span>
    <span class="font-normal text-neutral-300">{{ realStatusText }}</span>
  </div>
</template>
