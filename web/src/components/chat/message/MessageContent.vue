<script setup lang="ts">
import { computed, provide } from 'vue'
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

/** Extract ChunkCitation[] from the rag_search tool output */
function getChunkCitations(part: Parameters<typeof getToolName>[0]): ChunkCitation[] {
  const output = part.output
  if (!output) return []
  if (Array.isArray(output) && output.length > 0 && 'doc_id' in output[0]) {
    return output as ChunkCitation[]
  }
  return []
}

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

const mergedParts = computed(() => getMergedParts(props.message.parts))

const reasoningPart = computed(() => {
  return mergedParts.value.find(p => isReasoningUIPart(p))
})

const ragToolPart = computed(() => {
  return mergedParts.value.find(p => isToolUIPart(p) && ['rag_search', 'web_search', 'google_search'].includes(getToolName(p)))
})

const remainingParts = computed(() => {
  return mergedParts.value.filter(p => p !== reasoningPart.value && p !== ragToolPart.value)
})
</script>

<template>
  <!-- Top meta row for assistant: Thought on left, Knowledge search on right -->
  <div
    v-if="reasoningPart || ragToolPart"
    class="flex flex-wrap items-start gap-x-6 gap-y-2 mb-2 w-full"
  >
    <UChatReasoning
      v-if="reasoningPart"
      :text="reasoningPart.text"
      :streaming="isPartStreaming(reasoningPart)"
      chevron="leading"
      class="w-auto max-w-full my-0.5"
      :ui="{
        root: 'w-auto max-w-full',
        trigger: 'text-sm font-medium text-neutral-300 hover:text-neutral-100 transition-colors py-1 cursor-pointer select-none',
        label: 'text-sm font-medium text-neutral-300',
        chevronIcon: 'size-4 text-neutral-400'
      }"
    >
      <ChatComark
        :markdown="reasoningPart.text"
        :streaming="isPartStreaming(reasoningPart)"
      />
    </UChatReasoning>

    <UChatTool
      v-if="ragToolPart"
      :text="isToolStreaming(ragToolPart) ? '正在检索知识库...' : '已检索知识库'"
      :streaming="isToolStreaming(ragToolPart)"
      chevron="leading"
      class="w-auto max-w-full my-0.5"
      :ui="{
        root: 'w-auto max-w-full',
        trigger: 'text-sm font-medium text-neutral-300 hover:text-neutral-100 transition-colors py-1 cursor-pointer select-none',
        label: 'text-sm font-medium text-neutral-300',
        chevronIcon: 'size-4 text-neutral-400'
      }"
    >
      <ChatToolSources :citations="getChunkCitations(ragToolPart)" />
    </UChatTool>
  </div>

  <!-- Remaining content parts (Charts, Weather, Answer Text, User Edits) -->
  <template
    v-for="(part, index) in remainingParts"
    :key="`${message.id}-${part.type}-${index}`"
  >
    <template v-if="isToolUIPart(part)">
      <ChatToolChart
        v-if="getToolName(part) === 'chart'"
        :invocation="{ ...(part as ChartUIToolInvocation) }"
      />
      <ChatToolWeather
        v-else-if="getToolName(part) === 'weather'"
        :invocation="{ ...(part as WeatherUIToolInvocation) }"
      />
    </template>

    <template v-else-if="isTextUIPart(part)">
      <ChatComark
        v-if="message.role === 'assistant'"
        :markdown="part.text"
        :streaming="isPartStreaming(part)"
      />
      <template v-else-if="message.role === 'user'">
        <ChatMessageEdit
          v-if="editing"
          :message="message"
          :text="part.text"
          @save="(msg, text) => emit('save', msg, text)"
          @cancel="emit('cancelEdit')"
        />
        <p
          v-else
          class="whitespace-pre-wrap"
        >
          {{ part.text }}
        </p>
      </template>
    </template>
  </template>
</template>
