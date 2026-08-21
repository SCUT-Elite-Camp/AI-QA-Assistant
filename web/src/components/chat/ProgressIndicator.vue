<script setup lang="ts">
import { computed } from 'vue'
import type { UIMessage } from 'ai'

const props = defineProps<{
  status?: string
  messages?: UIMessage[]
}>()

const isCurrentAssistantPresent = computed(() => {
  const msgs = props.messages ?? []
  const lastMsg = msgs[msgs.length - 1]
  return lastMsg && lastMsg.role === 'assistant' && lastMsg.parts && lastMsg.parts.length > 0
})
</script>

<template>
  <div v-if="!isCurrentAssistantPresent" class="my-2.5 select-none">
    <div class="relative pl-6 py-1 flex flex-col gap-2.5">
      <!-- Vertical connecting line -->
      <div class="absolute left-[9px] top-2.5 bottom-2.5 w-[1.5px] bg-neutral-800"></div>

      <!-- Step 1: Intention & Problem Analysis -->
      <div class="relative flex items-center gap-2.5 text-sm">
        <div class="absolute -left-6 flex items-center justify-center w-5 h-5 rounded-full bg-neutral-950 text-amber-400">
          <UIcon name="i-lucide-lightbulb" class="w-4 h-4 text-amber-400 animate-pulse" />
        </div>
        <span class="text-neutral-200 font-normal">分析用户提问与意图...</span>
      </div>
    </div>

    <!-- Bottom: 思考中... like Grok -->
    <div class="mt-2.5 flex items-center gap-3">
      <span class="text-xs text-neutral-400 font-sans animate-pulse">思考中...</span>
    </div>
  </div>
</template>

