<script setup lang="ts">
import { computed, provide } from 'vue'
import { isReasoningUIPart, isTextUIPart, isToolUIPart, getToolName } from 'ai'
import type { UIMessage } from 'ai'
import { isPartStreaming } from '@nuxt/ui/utils/ai'
import ChatComark from '../Comark'
import ChatToolChart from '../tool/Chart.vue'
import ChatToolWeather from '../tool/Weather.vue'
import ChatMessageEdit from './MessageEdit.vue'
import ThinkingProcess from '../ThinkingProcess.vue'
import { getMergedParts } from '../../../utils/ai'
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
    <!-- Grok-style Step-by-Step Thinking Process & Timeline -->
    <ThinkingProcess :message="message" />

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
