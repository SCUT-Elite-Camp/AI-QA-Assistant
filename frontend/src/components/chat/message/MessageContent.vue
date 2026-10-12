<script setup lang="ts">
import { computed, provide, ref, nextTick } from 'vue'
import { isReasoningUIPart, isTextUIPart, isToolUIPart, getToolName } from 'ai'
import type { UIMessage } from 'ai'
import { isPartStreaming } from '@nuxt/ui/utils/ai'
import ChatComark from '../Comark'
import ChatToolChart from '../tool/Chart.vue'
import ChatToolWeather from '../tool/Weather.vue'
import ChatMessageEdit from './MessageEdit.vue'
import ChatModalDocumentViewer from '../ModalDocumentViewer.vue'
import { getMergedParts } from '../../../utils/ai'
import { formatResearchCitations } from '../../../utils/researchMarkdown'
import type { WeatherUIToolInvocation } from '../../../../server/utils/tools/weather'
import type { ChartUIToolInvocation } from '../../../../server/utils/tools/chart'
import type { ChunkCitation } from '../tool/Sources.vue'

const props = defineProps<{
  message: UIMessage
  editing: boolean
}>()

const emit = defineEmits<{
  save: [message: UIMessage, text: string]
  cancelEdit: []
}>()

/** Extract ChunkCitation[] from the rag_search tool output */
function getChunkCitations(part: Parameters<typeof getToolName>[0]): ChunkCitation[] {
  const output = part.output
  if (!output) return []
  if (Array.isArray(output) && output.length > 0 && 'doc_id' in output[0]) {
    return output as ChunkCitation[]
  }
  return []
}

/** Other parts to render sequentially (charts, weather, text markdown) */
const otherParts = computed(() => {
  return getMergedParts(props.message.parts ?? []).filter(part => {
    if (isReasoningUIPart(part)) return false
    if (isToolUIPart(part) && (getToolName(part) === 'rag_search' || getToolName(part) === 'web_search' || getToolName(part) === 'google_search')) return false
    return true
  })
})

/**
 * Build a Map<index, ChunkCitation> from all rag_search tool parts.
 * CiteMark components inject this to get tooltip data by index.
 */
const citationMap = computed(() => {
  const map = new Map<number, ChunkCitation>()
  for (const part of props.message.parts ?? []) {
    if (isToolUIPart(part) && getToolName(part) === 'rag_search') {
      for (const cit of getChunkCitations(part)) {
        map.set(Number(cit.index), cit)
      }
    }
  }
  return map
})

const hasTextContent = computed(() => {
  return otherParts.value.some(part => isTextUIPart(part) && (part.text || '').trim().length > 0)
})

interface AttachmentPartData {
  attachment_id?: string
  filename?: string
  mime_type?: string
  status?: string
  accepted_review?: boolean
}

const userAttachments = computed<AttachmentPartData[]>(() => {
  if (props.message.role !== 'user' || !Array.isArray(props.message.parts)) return []
  return (props.message.parts as any[])
    .filter(part => part && typeof part === 'object' && part.type === 'data-attachment' && part.data)
    .map(part => part.data as AttachmentPartData)
})

// Make citations available to all CiteMark children via inject
provide('ragCitationMap', citationMap)
const selectedCitation = ref<ChunkCitation | null>(null)
const citationOpen = ref(false)
let citationTrigger: HTMLElement | null = null
provide('openCitation', (index: number) => {
  selectedCitation.value = citationMap.value.get(index) ?? null
  if (!selectedCitation.value) return
  citationTrigger = document.activeElement instanceof HTMLElement ? document.activeElement : null
  citationOpen.value = true
})
async function setCitationOpen(open: boolean) {
  citationOpen.value = open
  if (!open) {
    await nextTick()
    citationTrigger?.focus()
  }
}
</script>

<template>
  <!-- User Message -->
  <template v-if="message.role === 'user'">
    <!-- Attached Files (if any) -->
    <div
      v-if="userAttachments.length"
      class="flex flex-wrap gap-2 mb-2 w-full"
    >
      <div
        v-for="att in userAttachments"
        :key="att.attachment_id || att.filename"
        class="inline-flex items-center gap-2 max-w-xs rounded-xl border border-zinc-200/80 dark:border-zinc-700/80 bg-white/80 dark:bg-zinc-800/80 backdrop-blur-sm px-3 py-1.5 text-xs shadow-xs"
      >
        <UIcon
          :name="att.mime_type?.startsWith('image/') ? 'i-lucide-image' : 'i-lucide-file-text'"
          class="w-4 h-4 shrink-0 text-primary"
        />
        <div class="flex flex-col min-w-0">
          <span class="truncate font-medium text-zinc-800 dark:text-zinc-200" :title="att.filename">
            {{ att.filename }}
          </span>
        </div>
      </div>
    </div>

    <template v-for="(part, index) in getMergedParts(message.parts)" :key="`${message.id}-${part.type}-${index}`">
      <ChatMessageEdit
        v-if="editing && isTextUIPart(part)"
        :message="message"
        :text="part.text"
        @save="(msg, text) => emit('save', msg, text)"
        @cancel="emit('cancelEdit')"
      />
      <p
        v-else-if="isTextUIPart(part)"
        class="whitespace-pre-wrap"
      >
        {{ part.text }}
      </p>
    </template>
  </template>

  <!-- Assistant Message -->
  <template v-else-if="message.role === 'assistant'">
    <!-- Processing... Sonar Pulse Indicator (shown while waiting for first tokens) -->
    <div
      v-if="!hasTextContent"
      class="flex items-center gap-3 py-1 text-zinc-400 select-none animate-in fade-in duration-200"
    >
      <div class="relative flex items-center justify-center w-5 h-5 shrink-0">
        <span
          class="absolute inline-flex h-full w-full rounded-full bg-zinc-400/25 dark:bg-zinc-500/30 animate-ping opacity-75"
          style="animation-duration: 1.8s;"
        />
        <span class="relative inline-flex rounded-full h-2 w-2 bg-zinc-400 dark:bg-zinc-300 shadow-[0_0_6px_rgba(161,161,170,0.5)]" />
      </div>
      <span class="text-xs sm:text-sm font-medium tracking-wide text-zinc-400 dark:text-zinc-400 select-none">
        Processing...
      </span>
    </div>

    <!-- Other Assistant Parts (Charts, Weather, and Main Text) -->
    <template
      v-for="(part, index) in otherParts"
      :key="`${message.id}-${part.type}-${index}`"
    >
      <ChatToolChart
        v-if="isToolUIPart(part) && getToolName(part) === 'chart'"
        :invocation="{ ...(part as ChartUIToolInvocation) }"
      />
      <ChatToolWeather
        v-else-if="isToolUIPart(part) && getToolName(part) === 'weather'"
        :invocation="{ ...(part as WeatherUIToolInvocation) }"
      />
      <ChatComark
        v-else-if="isTextUIPart(part)"
        :markdown="citationMap.size ? formatResearchCitations(part.text, new Set(citationMap.keys())) : part.text"
        :streaming="isPartStreaming(part)"
      />
    </template>
  </template>
  <ChatModalDocumentViewer :open="citationOpen" :doc="selectedCitation" :message-id="message.id" @update:open="setCitationOpen" />
</template>
