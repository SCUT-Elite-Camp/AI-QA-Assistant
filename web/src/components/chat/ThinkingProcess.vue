<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type { UIMessage } from 'ai'
import { isReasoningUIPart, isTextUIPart, isToolUIPart, getToolName } from 'ai'
import { isPartStreaming, isToolStreaming } from '@nuxt/ui/utils/ai'
import ChatComark from './Comark'
import ChatToolSources from './tool/Sources.vue'
import type { ChunkCitation } from './tool/Sources.vue'

const props = defineProps<{
  message: UIMessage
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
    }
  } else if (wasStreaming) {
    if (reasoningStartTime.value) {
      reasoningDuration.value = Math.max(1, Math.ceil((Date.now() - reasoningStartTime.value) / 1000))
      reasoningStartTime.value = null
    }
  }
}, { immediate: true })

const displayDuration = computed(() => {
  if (reasoningDuration.value) {
    return `${reasoningDuration.value}s`
  }
  const rPart = props.message.parts?.find(isReasoningUIPart)
  if (rPart && (rPart as any).text) {
    const textLen = (rPart as any).text.length
    const est = Math.max(2, Math.round(textLen / 25))
    return `${est}s`
  }
  return '2s'
})

/** Extract ChunkCitation[] from the rag_search tool output */
function getChunkCitations(part: any): ChunkCitation[] {
  if (!part) return []
  const output = part.output
  if (!output) return []
  if (Array.isArray(output) && output.length > 0 && 'doc_id' in output[0]) {
    return output as ChunkCitation[]
  }
  return []
}

/** Knowledge search tool part */
const searchPart = computed(() => {
  return props.message.parts?.find(p => isToolUIPart(p) && (getToolName(p) === 'rag_search' || getToolName(p) === 'web_search' || getToolName(p) === 'google_search'))
})

/** Reasoning thinking part */
const reasoningPart = computed(() => {
  return props.message.parts?.find(isReasoningUIPart)
})

/** Text response part */
const textPart = computed(() => {
  return props.message.parts?.find(isTextUIPart)
})

const citations = computed<ChunkCitation[]>(() => {
  return getChunkCitations(searchPart.value)
})

const isSearchActive = computed(() => {
  return searchPart.value ? isToolStreaming(searchPart.value) : false
})

const isReasoningActive = computed(() => {
  return reasoningPart.value ? isPartStreaming(reasoningPart.value) : false
})

const isTextActive = computed(() => {
  return textPart.value ? isPartStreaming(textPart.value) : false
})

/**
 * Extract dynamic sub-step titles from reasoning text if formatted with headers/bullet points
 */
const dynamicSubSteps = computed(() => {
  const text = (reasoningPart.value as any)?.text || ''
  if (!text) return []
  
  const lines = text.split('\n')
  const steps: string[] = []
  
  for (const line of lines) {
    const trimmed = line.trim()
    if (/^#{1,4}\s+(.+)$/.test(trimmed)) {
      const match = trimmed.replace(/^#{1,4}\s+/, '').replace(/^[\d+.]\s*/, '').trim()
      if (match && match.length > 2 && match.length < 35 && !steps.includes(match)) {
        steps.push(match)
      }
    }
  }
  return steps.slice(0, 4)
})
</script>

<template>
  <div v-if="searchPart || reasoningPart" class="my-2 select-none">
    <!-- Grok-style Vertical Step Tree -->
    <div class="relative pl-6 py-1 flex flex-col gap-2.5">
      <!-- Vertical connecting line -->
      <div class="absolute left-[9px] top-2.5 bottom-2.5 w-[1.5px] bg-neutral-800"></div>

      <!-- Step 1: Intention & Problem Analysis (Root Lightbulb Node) -->
      <div class="relative flex items-center gap-2.5 text-sm">
        <div class="absolute -left-6 flex items-center justify-center w-5 h-5 rounded-full bg-neutral-950 text-amber-400">
          <UIcon name="i-lucide-lightbulb" class="w-4 h-4 text-amber-400" />
        </div>
        <span class="text-neutral-200 font-normal">分析用户提问与意图</span>
      </div>

      <!-- Step 2: Knowledge Base Retrieval (if present) -->
      <div v-if="searchPart" class="relative flex items-center gap-2.5 text-sm">
        <div class="absolute -left-6 flex items-center justify-center w-5 h-5 rounded-full bg-neutral-950 text-neutral-400">
          <UIcon v-if="isSearchActive" name="i-lucide-loader-2" class="w-3.5 h-3.5 animate-spin text-emerald-400" />
          <div v-else class="w-2.5 h-2.5 rounded-full border border-neutral-600 bg-neutral-950"></div>
        </div>
        <div class="flex items-center gap-2 flex-wrap">
          <span :class="isSearchActive ? 'text-emerald-400 font-medium animate-pulse' : 'text-neutral-300'">
            {{ isSearchActive ? '正在检索知识库文档...' : `已检索知识库 (${citations.length} 个切块)` }}
          </span>
          <button
            v-if="citations.length > 0 && !isSearchActive"
            type="button"
            class="text-xs text-emerald-400 hover:text-emerald-300 underline underline-offset-2 cursor-pointer transition-colors"
            @click="isSourcesOpen = !isSourcesOpen"
          >
            {{ isSourcesOpen ? '收起切块' : '查看切块' }}
          </button>
        </div>
      </div>

      <!-- Step 3: Deep Reasoning Thinking (if present) -->
      <div v-if="reasoningPart" class="relative flex items-center gap-2.5 text-sm">
        <div class="absolute -left-6 flex items-center justify-center w-5 h-5 rounded-full bg-neutral-950 text-neutral-400">
          <UIcon v-if="isReasoningActive" name="i-lucide-loader-2" class="w-3.5 h-3.5 animate-spin text-neutral-300" />
          <div v-else class="w-2.5 h-2.5 rounded-full border border-neutral-600 bg-neutral-950"></div>
        </div>
        <div class="flex items-center gap-2">
          <span :class="isReasoningActive ? 'text-neutral-200 font-medium' : 'text-neutral-300'">
            {{ isReasoningActive ? '正在深度思考与推理...' : '多维深度推理与综合分析' }}
          </span>
        </div>
      </div>

      <!-- Optional: Dynamic sub-steps extracted from reasoning headings -->
      <div
        v-for="(stepText, idx) in dynamicSubSteps"
        :key="idx"
        class="relative flex items-center gap-2.5 text-sm pl-0.5"
      >
        <div class="absolute -left-6 flex items-center justify-center w-5 h-5 rounded-full bg-neutral-950">
          <div class="w-2 h-2 rounded-full border border-neutral-700 bg-neutral-950"></div>
        </div>
        <span class="text-neutral-400 text-xs">{{ stepText }}</span>
      </div>

      <!-- Step 4: Answer Organization (when text starts streaming or is ready) -->
      <div v-if="textPart && !isReasoningActive" class="relative flex items-center gap-2.5 text-sm">
        <div class="absolute -left-6 flex items-center justify-center w-5 h-5 rounded-full bg-neutral-950 text-neutral-400">
          <div class="w-2.5 h-2.5 rounded-full border border-neutral-600 bg-neutral-950"></div>
        </div>
        <span :class="isTextActive ? 'text-neutral-200' : 'text-neutral-400'">
          {{ isTextActive ? '正在组织并生成回答...' : '回答生成完成' }}
        </span>
      </div>
    </div>

    <!-- Bottom: 思考了 Xs (Thought for 19s) toggle button like Grok -->
    <div class="mt-2.5 flex items-center gap-3">
      <button
        type="button"
        class="inline-flex items-center gap-1.5 text-xs text-neutral-400 hover:text-neutral-200 transition-colors py-0.5 cursor-pointer font-sans"
        @click="isReasoningOpen = !isReasoningOpen"
      >
        <UIcon
          name="i-lucide-chevron-down"
          class="size-3.5 text-neutral-400 transition-transform duration-200"
          :class="{ '-rotate-90': !isReasoningOpen }"
        />
        <span>{{ isReasoningActive ? '思考中...' : `思考了 ${displayDuration}` }}</span>
      </button>
    </div>

    <!-- Collapsible Document Sources Card -->
    <div v-if="isSourcesOpen && citations.length > 0" class="w-full mt-2">
      <ChatToolSources :citations="citations" />
    </div>

    <!-- Collapsible Thinking Process Trace Panel -->
    <div
      v-if="isReasoningOpen && (reasoningPart as any)?.text"
      class="w-full mt-2 p-3.5 rounded-xl bg-neutral-900/60 border border-neutral-800/80 text-xs text-neutral-300 font-sans"
    >
      <ChatComark
        :markdown="(reasoningPart as any).text"
        :streaming="isReasoningActive"
      />
    </div>
  </div>
</template>
