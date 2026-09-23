<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, inject } from 'vue'
import type { UIMessage } from 'ai'
import { isReasoningUIPart, isTextUIPart, isToolUIPart, getToolName } from 'ai'
import { isPartStreaming, isToolStreaming } from '@nuxt/ui/utils/ai'
import ChatComark from './Comark'
import ChatToolSources from './tool/Sources.vue'
import type { ChunkCitation } from './tool/Sources.vue'
import ModalDocumentViewer from './ModalDocumentViewer.vue'

const props = defineProps<{
  message: UIMessage | null
  status?: 'submitted' | 'streaming' | 'ready' | 'error'
}>()

const isChatStreaming = inject<any>('is-chat-streaming', ref(false))

// Window Visibility & Collapse States
const isWindowOpen = ref(true)
const isWindowMinimized = ref(false)

const isSourcesOpen = ref(false)
const isReasoningOpen = ref(false)
const isStepTreeOpen = ref(true)

const isDocViewerOpen = ref(false)
const selectedDoc = ref<ChunkCitation | null>(null)

function toggleMinimize() {
  isWindowMinimized.value = !isWindowMinimized.value
}

function closeWindow() {
  isWindowOpen.value = false
}

function openWindow() {
  isWindowOpen.value = true
  isWindowMinimized.value = false
}

function toggleStepTree() {
  isStepTreeOpen.value = !isStepTreeOpen.value
}

// Step staggered progression stage (1: Query Analysis, 2: Knowledge Search, 3: Deep Reasoning, 4: Response Generation)
const stepStage = ref<number>(1)

// Timing
const reasoningStartTime = ref<number | null>(null)
const reasoningDuration = ref<number | null>(null)
const liveTimer = ref<number>(0)
let timerInterval: any = null

// Real-time Text Streaming Activity Tracker
const isTextActivelyReceiving = ref<boolean>(false)
let textActivityTimeout: any = null

/** Knowledge search tool part */
const searchPart = computed(() => {
  if (!props.message) return undefined
  return props.message.parts?.find(p => isToolUIPart(p) && (getToolName(p) === 'rag_search' || getToolName(p) === 'web_search' || getToolName(p) === 'google_search'))
})

/** Reasoning thinking part */
const reasoningPart = computed(() => {
  if (!props.message) return undefined
  return props.message.parts?.find(isReasoningUIPart)
})

/** Text response part */
const textPart = computed(() => {
  if (!props.message) return undefined
  return props.message.parts?.find(isTextUIPart)
})

/** Extract ChunkCitation[] from any tool part */
function getChunkCitationsFromPart(part: any): ChunkCitation[] {
  if (!part) return []
  const raw = part.output ?? part.result ?? part.toolInvocation?.result ?? part.toolInvocation?.output
  if (!raw) return []
  if (Array.isArray(raw)) {
    return raw.filter(item => item && typeof item === 'object') as ChunkCitation[]
  }
  if (typeof raw === 'object' && Array.isArray(raw.citations)) {
    return raw.citations.filter((item: any) => item && typeof item === 'object') as ChunkCitation[]
  }
  return []
}

const citations = computed<ChunkCitation[]>(() => {
  if (!props.message) return []
  const list: ChunkCitation[] = []
  for (const part of props.message.parts ?? []) {
    const items = getChunkCitationsFromPart(part)
    if (items.length > 0) {
      list.push(...items)
    }
  }
  return list
})

/**
 * Deduplicate citations by doc_id / title to display distinct document pills in the ticker
 */
const uniqueDocuments = computed(() => {
  const seen = new Set<string>()
  const list: ChunkCitation[] = []
  for (const cit of citations.value) {
    const key = cit.title || cit.doc_id || `doc_${list.length}`
    if (!seen.has(key)) {
      seen.add(key)
      list.push(cit)
    }
  }
  return list
})

function formatDocName(title?: string, docId?: string, idx: number = 0): string {
  if (title && !/^[0-9a-f]{20,}$/i.test(title)) {
    return title
  }
  if (docId && !/^[0-9a-f]{20,}$/i.test(docId)) {
    return docId
  }
  return `Document #${idx + 1}`
}

function getDocIcon(title?: string, docId?: string): string {
  const name = (title || docId || '').toLowerCase()
  if (name.endsWith('.md') || name.endsWith('.markdown')) return 'i-lucide-file-text'
  if (name.endsWith('.pdf')) return 'i-lucide-file-type'
  if (name.endsWith('.py') || name.endsWith('.ts') || name.endsWith('.js') || name.endsWith('.vue') || name.endsWith('.json') || name.endsWith('.sql')) return 'i-lucide-file-code'
  if (name.startsWith('http://') || name.startsWith('https://')) return 'i-lucide-globe'
  return 'i-lucide-file-text'
}

/**
 * Remap raw retrieval scores (RRF / Cosine / BM25) to a calibrated 0-100% relevance score.
 */
function getRelevanceScore(rawScore?: number | null, index: number = 0): number {
  if (rawScore === null || rawScore === undefined || isNaN(rawScore) || rawScore <= 0) {
    return Math.max(65, 96 - index * 5)
  }

  if (rawScore <= 0.06) {
    const ratio = Math.min(1.0, Math.max(0.0, (rawScore - 0.010) / 0.023))
    const calibrated = 76 + ratio * 22
    return Math.round(Math.min(99, Math.max(65, calibrated)))
  }

  if (rawScore <= 1.0) {
    const ratio = Math.min(1.0, Math.max(0.0, (rawScore - 0.35) / 0.55))
    const calibrated = 72 + ratio * 26
    return Math.round(Math.min(99, Math.max(65, calibrated)))
  }

  if (rawScore > 1.0 && rawScore <= 100) {
    if (rawScore > 50) return Math.round(rawScore)
    const ratio = rawScore / (rawScore + 6)
    return Math.round(Math.min(99, Math.max(65, 65 + ratio * 33)))
  }

  return Math.max(65, 96 - index * 5)
}

function handlePillClick(doc: ChunkCitation) {
  selectedDoc.value = doc
  isDocViewerOpen.value = true
}

// Staggered sequential reveal of document pills
const visibleDocuments = ref<ChunkCitation[]>([])
const pendingPillTimers: any[] = []

function clearPillTimers() {
  while (pendingPillTimers.length > 0) {
    clearTimeout(pendingPillTimers.pop())
  }
}

function syncVisibleDocuments(targetDocs: ChunkCitation[], isLive: boolean) {
  if (!isLive) {
    clearPillTimers()
    visibleDocuments.value = [...targetDocs]
    return
  }

  if (targetDocs.length === 0) {
    clearPillTimers()
    visibleDocuments.value = []
    return
  }

  if (visibleDocuments.value.length === targetDocs.length) return

  const startIndex = visibleDocuments.value.length
  for (let i = startIndex; i < targetDocs.length; i++) {
    const docToPush = targetDocs[i]
    const delay = (i - startIndex) * 400
    const timer = setTimeout(() => {
      if (docToPush && !visibleDocuments.value.some(d => (d.doc_id || d.title) === (docToPush.doc_id || docToPush.title))) {
        visibleDocuments.value.push(docToPush)
      }
    }, delay)
    pendingPillTimers.push(timer)
  }
}

watch(
  () => uniqueDocuments.value,
  (docs) => {
    syncVisibleDocuments(docs, isChatStreaming.value || props.status === 'streaming')
  },
  { immediate: true, deep: true }
)

// Real-time streaming status
const isSearchStreaming = computed(() => {
  if (citations.value.length > 0) return false
  if (!searchPart.value) return false
  if (isChatStreaming.value === false && props.status !== 'streaming') return false
  if (textPart.value || (reasoningPart.value && (reasoningPart.value as any).text)) return false
  return isToolStreaming(searchPart.value)
})

const isReasoningStreaming = computed(() => {
  if (!reasoningPart.value) return false
  if (isChatStreaming.value === false && props.status !== 'streaming') return false
  if (textPart.value && (textPart.value as any).text) return false
  return isPartStreaming(reasoningPart.value)
})

const isTextStreaming = computed(() => {
  if (!textPart.value) return false
  if (isChatStreaming.value === false && props.status !== 'streaming') return false
  const state = (textPart.value as any)?.state
  if (state === 'done' || state === 'complete' || state === 'output-available') return false
  return isTextActivelyReceiving.value
})

const isAnyActive = computed(() => {
  return isSearchStreaming.value || isReasoningStreaming.value || isTextStreaming.value || props.status === 'streaming'
})

// Watch text changes to track active stream bursts
watch(
  () => (textPart.value as any)?.text,
  (newText, oldText) => {
    if (newText && newText !== oldText) {
      isTextActivelyReceiving.value = true
      if (textActivityTimeout) clearTimeout(textActivityTimeout)
      textActivityTimeout = setTimeout(() => {
        isTextActivelyReceiving.value = false
      }, 700)
    }
  },
  { immediate: true }
)

// Calculate duration
const displayDuration = computed(() => {
  if (reasoningDuration.value) {
    return `${reasoningDuration.value}s`
  }
  const rPart = reasoningPart.value
  if (rPart && (rPart as any).text) {
    const textLen = (rPart as any).text.length
    const est = Math.max(1, Math.round(textLen / 25))
    return `${est}s`
  }
  return '1s'
})

// Watch message parts deeply so incoming stream parts dynamically advance the step tree in real-time
watch(
  () => props.message?.parts,
  (parts) => {
    if (!parts) {
      stepStage.value = 1
      return
    }
    const hasSearch = parts.some(p => isToolUIPart(p) && (getToolName(p) === 'rag_search' || getToolName(p) === 'web_search' || getToolName(p) === 'google_search'))
    const hasReasoning = parts.some(isReasoningUIPart)
    const hasText = parts.some(p => isTextUIPart(p) && !!(p as any).text)

    if (hasSearch && stepStage.value < 2) {
      setTimeout(() => {
        stepStage.value = Math.max(stepStage.value, 2)
      }, 150)
    } else if (hasSearch) {
      stepStage.value = Math.max(stepStage.value, 2)
    }

    if (hasReasoning && stepStage.value < 3) {
      setTimeout(() => {
        stepStage.value = Math.max(stepStage.value, 3)
      }, 200)
    } else if (hasReasoning) {
      stepStage.value = Math.max(stepStage.value, 3)
    }

    if (hasText && stepStage.value < 4) {
      setTimeout(() => {
        stepStage.value = Math.max(stepStage.value, 4)
      }, 150)
    } else if (hasText) {
      stepStage.value = Math.max(stepStage.value, 4)
    }
  },
  { deep: true, immediate: true }
)

// Auto-expand and open on new stream submission
watch(
  () => props.status,
  (newStatus) => {
    if (newStatus === 'streaming' || newStatus === 'submitted') {
      isWindowOpen.value = true
      isWindowMinimized.value = false
    }
  }
)

watch(() => isReasoningStreaming.value, (streaming, wasStreaming) => {
  if (streaming) {
    if (!wasStreaming) {
      reasoningStartTime.value = Date.now()
      if (timerInterval) clearInterval(timerInterval)
      timerInterval = setInterval(() => {
        if (reasoningStartTime.value) {
          liveTimer.value = Math.max(1, Math.ceil((Date.now() - reasoningStartTime.value) / 1000))
        }
      }, 500)
    }
  } else if (wasStreaming) {
    if (reasoningStartTime.value) {
      reasoningDuration.value = Math.max(1, Math.ceil((Date.now() - reasoningStartTime.value) / 1000))
    }
    if (timerInterval) {
      clearInterval(timerInterval)
      timerInterval = null
    }
  }
})

onUnmounted(() => {
  if (timerInterval) clearInterval(timerInterval)
  if (textActivityTimeout) clearTimeout(textActivityTimeout)
  clearPillTimers()
})

// Stage expressions
const queryIntentActiveVariants = [
  'Analyzing the query intent...',
  'Deciphering your prompt...',
  'Deconstructing the inquiry...',
  'Parsing semantic nuances...',
  'Formulating thought approach...',
  'Mapping problem scope & context...',
  'Understanding key requirements...'
]

const queryIntentDoneVariants = [
  'Query intent analyzed',
  'Prompt deciphered',
  'Inquiry deconstructed',
  'Semantic context mapped',
  'Core requirements understood',
  'Intent parsed successfully'
]

const reasoningActiveVariants = [
  'Reasoning and synthesizing knowledge...',
  'Connecting factual dots...',
  'Cross-referencing evidence & citations...',
  'Synthesizing insights from documentation...',
  'Constructing logical deduction chain...'
]

const reasoningDoneVariants = [
  'Reasoning completed',
  'Insights synthesized',
  'Logical deduction verified',
  'Evidence cross-referenced',
  'Knowledge points distilled'
]

const writingActiveVariants = [
  'Writing response...',
  'Crafting detailed breakdown...',
  'Composing clear explanation...',
  'Generating tailored response...'
]

const writingDoneVariants = [
  'Response generated',
  'Answer ready',
  'Explanation finalized',
  'Output completed'
]

function getVariantIndex(seedStr: string, poolLength: number, salt: number = 0): number {
  if (!seedStr) return salt % poolLength
  let hash = 0
  for (let i = 0; i < seedStr.length; i++) {
    hash = (hash << 5) - hash + seedStr.charCodeAt(i) + salt
    hash |= 0
  }
  return Math.abs(hash) % poolLength
}

const variantSeed = computed(() => props.message?.id || 'seed_default')
const stage1Index = computed(() => getVariantIndex(variantSeed.value, queryIntentActiveVariants.length, 1))
const stage3Index = computed(() => getVariantIndex(variantSeed.value, reasoningActiveVariants.length, 7))
const stage4Index = computed(() => getVariantIndex(variantSeed.value, writingActiveVariants.length, 13))

const hasReasoningOrSearch = computed(() => {
  return Boolean(searchPart.value || reasoningPart.value || citations.value.length > 0)
})

defineExpose({
  openWindow,
  closeWindow,
  toggleMinimize
})
</script>

<template>
  <!-- Floating Reasoning Widget Container -->
  <div
    v-if="hasReasoningOrSearch && isWindowOpen"
    class="absolute top-4 right-4 z-30 select-none font-sans transition-all duration-300 pointer-events-auto"
  >
    <!-- Collapsed Pill View while Active Streaming -->
    <div
      v-if="isWindowMinimized && isAnyActive"
      class="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-neutral-900/90 hover:bg-neutral-800/90 border border-emerald-500/60 shadow-lg shadow-emerald-950/30 backdrop-blur-md text-xs cursor-pointer transition-all hover:scale-105 active:scale-95"
      title="点击展开实时推理小窗"
      @click="toggleMinimize"
    >
      <UIcon
        name="i-lucide-sparkles"
        class="w-3.5 h-3.5 text-emerald-400 animate-spin"
      />
      <span class="font-medium text-neutral-200">
        思考中...
      </span>
      <UIcon name="i-lucide-maximize-2" class="w-3 h-3 text-neutral-400 hover:text-neutral-200" />
    </div>

    <!-- Expanded Floating Small Window -->
    <div
      v-else-if="!isWindowMinimized"
      class="w-80 sm:w-96 max-h-[calc(100vh-160px)] flex flex-col rounded-2xl bg-neutral-950/95 border border-neutral-800 shadow-2xl backdrop-blur-xl overflow-hidden transition-all duration-300 animate-in fade-in zoom-in-95"
    >
      <!-- Top Window Header Bar -->
      <div class="flex items-center justify-between px-3.5 py-2.5 bg-neutral-900/80 border-b border-neutral-800/80 shrink-0">
        <div class="flex items-center gap-2 min-w-0">
          <div class="flex items-center justify-center w-5 h-5 rounded-md bg-neutral-800 text-amber-400">
            <UIcon name="i-lucide-brain" class="w-3.5 h-3.5" />
          </div>
          <span class="text-xs font-semibold text-neutral-100 tracking-wide truncate">
            实时推理过程
          </span>
          <!-- Live Status Indicator Badge -->
          <span
            v-if="isAnyActive"
            class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 animate-pulse"
          >
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
            {{ liveTimer > 0 ? `${liveTimer}s` : '思考中' }}
          </span>
        </div>

        <!-- Window Controls -->
        <div class="flex items-center gap-1 shrink-0">
          <button
            v-if="isAnyActive"
            type="button"
            class="p-1 rounded-md text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800 transition-colors cursor-pointer"
            title="最小化"
            @click="toggleMinimize"
          >
            <UIcon name="i-lucide-minus" class="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            class="p-1 rounded-md text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800 transition-colors cursor-pointer"
            title="关闭小窗"
            @click="closeWindow"
          >
            <UIcon name="i-lucide-x" class="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      <!-- Scrollable Window Content Body -->
      <div class="flex-1 overflow-y-auto p-3.5 space-y-3 custom-scrollbar text-xs">
        <!-- 4-Stage Step Tree -->
        <div class="relative pl-5 py-0.5 flex flex-col gap-2">
          <!-- Vertical Step Line -->
          <div v-show="isStepTreeOpen" class="absolute left-[7px] top-2 bottom-2 w-[1.5px] bg-neutral-800"></div>

          <!-- Step 1: Intention & Problem Analysis -->
          <div
            class="relative flex items-center gap-2 cursor-pointer select-none group/step py-0.5"
            @click="toggleStepTree"
          >
            <div class="absolute -left-5 flex items-center justify-center w-4 h-4 rounded-full bg-neutral-950 text-amber-400">
              <UIcon name="i-lucide-lightbulb" class="w-3 h-3 text-amber-400" />
            </div>
            <span class="text-neutral-200 font-medium group-hover/step:text-amber-300 transition-colors flex-1 truncate">
              {{ stepStage === 1 ? queryIntentActiveVariants[stage1Index] : queryIntentDoneVariants[stage1Index] }}
            </span>
            <UIcon
              name="i-lucide-chevron-down"
              class="w-3 h-3 text-neutral-500 group-hover/step:text-neutral-300 transition-transform duration-200"
              :class="{ '-rotate-90': !isStepTreeOpen }"
            />
          </div>

          <!-- Collapsible Steps -->
          <div v-show="isStepTreeOpen" class="flex flex-col gap-2 pt-0.5">
            <!-- Step 2: Knowledge Base Search -->
            <div v-if="searchPart || citations.length > 0 || stepStage >= 2" class="relative flex flex-col gap-1.5">
              <div class="flex items-center gap-2">
                <div class="absolute -left-5 flex items-center justify-center w-4 h-4 rounded-full bg-neutral-950 text-neutral-400">
                  <UIcon v-if="isSearchStreaming" name="i-lucide-loader-2" class="w-3 h-3 animate-spin text-emerald-400" />
                  <div v-else class="w-2 h-2 rounded-full border border-neutral-600 bg-neutral-950"></div>
                </div>
                <span :class="isSearchStreaming ? 'text-emerald-400 font-medium animate-pulse' : 'text-neutral-300'" class="truncate">
                  {{ isSearchStreaming ? 'Searching knowledge base...' : 'Knowledge base searched' }}
                </span>
                <span v-if="uniqueDocuments.length > 0" class="text-[10px] text-neutral-500 font-mono">
                  ({{ uniqueDocuments.length }} {{ uniqueDocuments.length === 1 ? 'doc' : 'docs' }})
                </span>
              </div>

              <!-- Document Pills Horizontal Ribbon -->
              <div v-if="visibleDocuments.length > 0" class="w-full overflow-hidden mt-0.5">
                <TransitionGroup
                  name="pill-stagger"
                  tag="div"
                  class="flex items-center gap-1.5 overflow-x-auto py-1 px-0.5 [mask-image:linear-gradient(to_right,black_calc(100%-20px),transparent_100%)]"
                >
                  <div
                    v-for="(doc, idx) in visibleDocuments"
                    :key="doc.doc_id || doc.name || idx"
                    class="group inline-flex items-center gap-1 px-2 py-0.5 rounded-md border border-neutral-800 bg-neutral-900/90 hover:bg-neutral-800 hover:border-emerald-500/40 text-[11px] text-neutral-300 hover:text-neutral-100 transition-all cursor-pointer shrink-0 max-w-[180px]"
                    :title="doc.title || doc.doc_id"
                    @click="handlePillClick(doc)"
                  >
                    <UIcon :name="getDocIcon(doc.title, doc.doc_id)" class="w-3 h-3 text-emerald-400 shrink-0" />
                    <span class="truncate">{{ formatDocName(doc.title, doc.doc_id, idx) }}</span>
                    <span class="text-[9px] font-mono text-emerald-400 shrink-0">{{ getRelevanceScore(doc.score, idx) }}%</span>
                  </div>
                </TransitionGroup>
              </div>
            </div>

            <!-- Step 3: Deep Reasoning Thinking -->
            <div v-if="reasoningPart || stepStage >= 3" class="relative flex items-center gap-2">
              <div class="absolute -left-5 flex items-center justify-center w-4 h-4 rounded-full bg-neutral-950 text-neutral-400">
                <UIcon v-if="isReasoningStreaming" name="i-lucide-loader-2" class="w-3 h-3 animate-spin text-neutral-300" />
                <div v-else class="w-2 h-2 rounded-full border border-neutral-600 bg-neutral-950"></div>
              </div>
              <span :class="isReasoningStreaming ? 'text-neutral-200 font-medium' : 'text-neutral-400'" class="truncate">
                {{ isReasoningStreaming ? reasoningActiveVariants[stage3Index] : reasoningDoneVariants[stage3Index] }}
              </span>
            </div>

            <!-- Step 4: Formulating Response -->
            <div v-if="textPart || stepStage >= 4" class="relative flex items-center gap-2">
              <div class="absolute -left-5 flex items-center justify-center w-4 h-4 rounded-full bg-neutral-950 text-neutral-400">
                <div class="w-2 h-2 rounded-full border border-neutral-600 bg-neutral-950"></div>
              </div>
              <span :class="isTextStreaming ? 'text-neutral-200 animate-pulse' : 'text-neutral-400'" class="truncate">
                {{ isTextStreaming ? writingActiveVariants[stage4Index] : writingDoneVariants[stage4Index] }}
              </span>
            </div>
          </div>
        </div>

        <!-- Collapsible Thinking Process Trace Accordion -->
        <div v-if="(reasoningPart as any)?.text" class="border-t border-neutral-800/80 pt-2.5">
          <button
            type="button"
            class="flex items-center justify-between w-full text-[11px] font-medium text-neutral-300 hover:text-neutral-100 py-1 cursor-pointer transition-colors"
            @click="isReasoningOpen = !isReasoningOpen"
          >
            <span class="inline-flex items-center gap-1.5">
              <UIcon name="i-lucide-file-code" class="w-3.5 h-3.5 text-neutral-400" />
              <span>思维链详情</span>
            </span>
            <UIcon
              name="i-lucide-chevron-down"
              class="w-3.5 h-3.5 text-neutral-500 transition-transform duration-200"
              :class="{ '-rotate-90': !isReasoningOpen }"
            />
          </button>

          <div
            v-if="isReasoningOpen"
            class="mt-1.5 p-2.5 rounded-xl bg-neutral-900/80 border border-neutral-800 text-[11px] text-neutral-300 max-h-48 overflow-y-auto custom-scrollbar"
          >
            <ChatComark
              :markdown="(reasoningPart as any).text"
              :streaming="isReasoningStreaming"
            />
          </div>
        </div>

        <!-- Collapsible Retrieved Sources Accordion -->
        <div v-if="citations.length > 0" class="border-t border-neutral-800/80 pt-2.5">
          <button
            type="button"
            class="flex items-center justify-between w-full text-[11px] font-medium text-neutral-300 hover:text-neutral-100 py-1 cursor-pointer transition-colors"
            @click="isSourcesOpen = !isSourcesOpen"
          >
            <span class="inline-flex items-center gap-1.5">
              <UIcon name="i-lucide-library" class="w-3.5 h-3.5 text-emerald-400" />
              <span>检索知识库来源 ({{ citations.length }})</span>
            </span>
            <UIcon
              name="i-lucide-chevron-down"
              class="w-3.5 h-3.5 text-neutral-500 transition-transform duration-200"
              :class="{ '-rotate-90': !isSourcesOpen }"
            />
          </button>

          <div v-if="isSourcesOpen" class="mt-1.5">
            <ChatToolSources :citations="citations" @select-doc="handlePillClick" />
          </div>
        </div>
      </div>
    </div>

    <!-- Document Viewer Modal -->
    <ModalDocumentViewer
      v-model:open="isDocViewerOpen"
      :doc="selectedDoc"
      :all-citations="citations"
    />
  </div>
</template>

<style scoped>
.pill-stagger-enter-active {
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}
.pill-stagger-enter-from {
  opacity: 0;
  transform: translateX(8px) scale(0.95);
}
.pill-stagger-enter-to {
  opacity: 1;
  transform: translateX(0) scale(1);
}

.custom-scrollbar::-webkit-scrollbar {
  width: 4px;
  height: 4px;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.15);
  border-radius: 4px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.3);
}
</style>
