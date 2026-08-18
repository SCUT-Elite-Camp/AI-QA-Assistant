<script setup lang="ts">
import { ref, computed, watch, provide } from 'vue'
import { isReasoningUIPart, isTextUIPart, isToolUIPart, getToolName } from 'ai'
import type { UIMessage } from 'ai'
import { isPartStreaming, isToolStreaming } from '@nuxt/ui/utils/ai'
import ChatComark from '../Comark'
import ChatToolChart from '../tool/Chart.vue'
import ChatToolWeather from '../tool/Weather.vue'
import ChatToolSources from '../tool/Sources.vue'
import type { ChunkCitation } from '../tool/Sources.vue'
import ChatMessageEdit from './MessageEdit.vue'
import { getMergedParts } from '../../../utils/ai'
import type { WeatherUIToolInvocation } from '../../../../server/utils/tools/weather'
import type { ChartUIToolInvocation } from '../../../../server/utils/tools/chart'

const props = defineProps<{
  message: UIMessage
  editing: boolean
}>()

const emit = defineEmits<{
  save: [message: UIMessage, text: string]
  cancelEdit: []
}>()

const isSourcesOpen = ref(false)
const isReasoningOpen = ref(false)

const reasoningStartTime = ref<number | null>(null)
const reasoningDuration = ref<number | null>(null)

watch(() => {
  const rPart = props.message.parts?.find(isReasoningUIPart)
  return rPart ? isPartStreaming(rPart) : false
}, (streaming, wasStreaming) => {
  if (streaming) {
    if (!wasStreaming) {
      reasoningStartTime.value = Date.now()
      isReasoningOpen.value = true
    }
  } else if (wasStreaming) {
    if (reasoningStartTime.value) {
      reasoningDuration.value = Math.max(1, Math.ceil((Date.now() - reasoningStartTime.value) / 1000))
      reasoningStartTime.value = null
    }
    setTimeout(() => {
      isReasoningOpen.value = false
    }, 400)
  }
}, { immediate: true })

const displayReasoningDuration = computed(() => {
  if (reasoningDuration.value) {
    return `${reasoningDuration.value} seconds`
  }
  const rPart = props.message.parts?.find(isReasoningUIPart)
  if (rPart && (rPart as any).text) {
    const textLen = (rPart as any).text.length
    const est = Math.max(2, Math.round(textLen / 25))
    return `${est} seconds`
  }
  return '2 seconds'
})

/** Extract ChunkCitation[] from the rag_search tool output */
function getChunkCitations(part: Parameters<typeof getToolName>[0]): ChunkCitation[] {
  const output = part.output
  if (!output) return []
  if (Array.isArray(output) && output.length > 0 && 'doc_id' in output[0]) {
    return output as ChunkCitation[]
  }
  return []
}

/** Extract tool part for knowledge base retrieval */
const toolSearchPart = computed(() => {
  return props.message.parts?.find(p => isToolUIPart(p) && (getToolName(p) === 'rag_search' || getToolName(p) === 'web_search' || getToolName(p) === 'google_search'))
})

/** Extract reasoning part */
const reasoningPart = computed(() => {
  return props.message.parts?.find(isReasoningUIPart)
})

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

// Make citations available to all CiteMark children via inject
provide('ragCitationMap', citationMap)
</script>

<template>
  <!-- User Message -->
  <template v-if="message.role === 'user'">
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
    <!-- Top Row: "已检索知识库" and "Thought for X seconds" placed side-by-side on the SAME line -->
    <div v-if="toolSearchPart || reasoningPart" class="flex flex-col gap-2 my-1.5">
      <div class="flex items-center gap-4 flex-wrap">
        <!-- 1. 已检索知识库 -->
        <button
          v-if="toolSearchPart"
          type="button"
          class="inline-flex items-center gap-1.5 text-sm font-medium text-neutral-300 hover:text-neutral-100 transition-colors py-1 cursor-pointer select-none"
          @click="isSourcesOpen = !isSourcesOpen"
        >
          <UIcon
            name="i-lucide-chevron-down"
            class="size-4 text-neutral-400 transition-transform duration-200"
            :class="{ '-rotate-90': !isSourcesOpen }"
          />
          <span>{{ isToolStreaming(toolSearchPart) ? '正在检索知识库...' : '已检索知识库' }}</span>
        </button>

        <!-- 2. Thought for X seconds on the RIGHT of 已检索知识库 on the same line -->
        <button
          v-if="reasoningPart"
          type="button"
          class="inline-flex items-center gap-1.5 text-sm font-medium text-neutral-300 hover:text-neutral-100 transition-colors py-1 cursor-pointer select-none"
          @click="isReasoningOpen = !isReasoningOpen"
        >
          <UIcon
            name="i-lucide-chevron-down"
            class="size-4 text-neutral-400 transition-transform duration-200"
            :class="{ '-rotate-90': !isReasoningOpen }"
          />
          <span v-if="isPartStreaming(reasoningPart)" class="animate-pulse">Thinking...</span>
          <span v-else>Thought for {{ displayReasoningDuration }}</span>
        </button>
      </div>

      <!-- Collapsible Knowledge Sources Card -->
      <div v-if="toolSearchPart && isSourcesOpen" class="w-full mt-1">
        <ChatToolSources :citations="getChunkCitations(toolSearchPart)" />
      </div>

      <!-- Collapsible Reasoning Thinking Chain Panel -->
      <div
        v-if="reasoningPart && isReasoningOpen"
        class="w-full mt-1 p-3.5 rounded-xl bg-neutral-900/60 border border-neutral-800/80 text-xs text-neutral-300 font-sans"
      >
        <ChatComark
          :markdown="reasoningPart.text"
          :streaming="isPartStreaming(reasoningPart)"
        />
      </div>
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
        :markdown="part.text"
        :streaming="isPartStreaming(part)"
      />
    </template>
  </template>
</template>
