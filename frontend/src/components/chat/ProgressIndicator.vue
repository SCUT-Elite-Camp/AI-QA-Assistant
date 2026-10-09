<script setup lang="ts">
import { computed } from 'vue'
import type { UIMessage } from 'ai'

const props = defineProps<{
  status?: string
  messages?: UIMessage[]
}>()

const isTextStreamingOrDone = computed(() => {
  const msgs = props.messages ?? []
  const lastMsg = msgs[msgs.length - 1]
  if (!lastMsg || lastMsg.role !== 'assistant') return false

  const textPart = lastMsg.parts?.find(
    (p: any) => p.type === 'text' && typeof p.text === 'string' && p.text.trim().length > 0
  )
  return Boolean(textPart)
})
</script>

<template>
  <div
    v-if="!isTextStreamingOrDone"
    class="my-2.5 flex items-center gap-3 py-1 text-zinc-400 select-none animate-in fade-in duration-200"
  >
    <!-- Claude-style Sonar Radar Pulse Ring -->
    <div class="relative flex items-center justify-center w-5 h-5 shrink-0">
      <span
        class="absolute inline-flex h-full w-full rounded-full bg-zinc-400/25 dark:bg-zinc-500/30 animate-ping opacity-75"
        style="animation-duration: 1.8s;"
      />
      <span class="relative inline-flex rounded-full h-2 w-2 bg-zinc-400 dark:bg-zinc-300 shadow-[0_0_6px_rgba(161,161,170,0.5)]" />
    </div>

    <!-- Processing Text -->
    <span class="text-xs sm:text-sm font-medium tracking-wide text-zinc-400 dark:text-zinc-400 select-none font-sans">
      Processing...
    </span>
  </div>
</template>
