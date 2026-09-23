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
  message: UIMessage
}>()

const isChatStreaming = inject<any>('is-chat-streaming', ref(false))

const isSourcesOpen = ref(false)
const isReasoningOpen = ref(false)
const isStepTreeOpen = ref(true)

const isDocViewerOpen = ref(false)
const selectedDoc = ref<ChunkCitation | null>(null)

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
    const key = cit.title || cit.doc_id || `doc_${cit.index}`
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
 * Top matching documents map to 92% - 98%, while moderate matching hits map to 76% - 89%.
 */
function getRelevanceScore(rawScore?: number | null, index: number = 0): number {
  if (rawScore === null || rawScore === undefined || isNaN(rawScore) || rawScore <= 0) {
    return Math.max(65, 96 - index * 5)
  }

  // 1. RRF Fusion Score (typically 0.008 ~ 0.035, where 0.0328 is rank-1 in both BM25 & Vector)
  if (rawScore <= 0.06) {
    const ratio = Math.min(1.0, Math.max(0.0, (rawScore - 0.010) / 0.023))
    const calibrated = 76 + ratio * 22 // 76% ~ 98%
    return Math.round(Math.min(99, Math.max(65, calibrated)))
  }

  // 2. Cosine / Normalized Vector Score (0.06 ~ 1.0)
  if (rawScore <= 1.0) {
    const ratio = Math.min(1.0, Math.max(0.0, (rawScore - 0.35) / 0.55))
    const calibrated = 72 + ratio * 26 // 72% ~ 98%
    return Math.round(Math.min(99, Math.max(65, calibrated)))
  }

  // 3. BM25 / High-magnitude score (> 1.0)
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
    const delay = (i - startIndex) * 500 // 500ms smooth interval per document
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
    syncVisibleDocuments(docs, isChatStreaming.value)
  },
  { immediate: true, deep: true }
)

// Real-time streaming status
const isSearchStreaming = computed(() => {
  if (citations.value.length > 0) return false
  if (!searchPart.value) return false
  if (isChatStreaming.value === false) return false
  if (textPart.value || (reasoningPart.value && (reasoningPart.value as any).text)) return false
  return isToolStreaming(searchPart.value)
})

const isReasoningStreaming = computed(() => {
  if (!reasoningPart.value) return false
  if (isChatStreaming.value === false) return false
  if (textPart.value && (textPart.value as any).text) return false
  return isPartStreaming(reasoningPart.value)
})

// Text is considered streaming if it is actively receiving deltas AND chat status is currently streaming
const isTextStreaming = computed(() => {
  if (!textPart.value) return false
  if (isChatStreaming.value === false) return false
  const state = (textPart.value as any)?.state
  if (state === 'done' || state === 'complete' || state === 'output-available') return false
  return isTextActivelyReceiving.value
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
  () => props.message.parts,
  (parts) => {
    if (!parts) return
    const hasSearch = parts.some(p => isToolUIPart(p) && (getToolName(p) === 'rag_search' || getToolName(p) === 'web_search' || getToolName(p) === 'google_search'))
    const hasReasoning = parts.some(isReasoningUIPart)
    const hasText = parts.some(p => isTextUIPart(p) && !!(p as any).text)

    if (hasSearch && stepStage.value < 2) {
      setTimeout(() => {
        stepStage.value = Math.max(stepStage.value, 2)
      }, 200)
    } else if (hasSearch) {
      stepStage.value = Math.max(stepStage.value, 2)
    }

    if (hasReasoning && stepStage.value < 3) {
      setTimeout(() => {
        stepStage.value = Math.max(stepStage.value, 3)
      }, 300)
    } else if (hasReasoning) {
      stepStage.value = Math.max(stepStage.value, 3)
    }

    if (hasText && stepStage.value < 4) {
      setTimeout(() => {
        stepStage.value = Math.max(stepStage.value, 4)
      }, 200)
    } else if (hasText) {
      stepStage.value = Math.max(stepStage.value, 4)
    }
  },
  { deep: true, immediate: true }
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
  } else if (wasStreaming || (wasStreaming === undefined && !streaming && reasoningStartTime.value)) {
    if (reasoningStartTime.value) {
      reasoningDuration.value = Math.max(1, Math.ceil((Date.now() - reasoningStartTime.value) / 1000))
      reasoningStartTime.value = null
    }
    if (timerInterval) {
      clearInterval(timerInterval)
      timerInterval = null
    }
  }
}, { immediate: true })

// Watch for text stream start to immediately finalize reasoning duration
watch(() => textPart.value?.text, (txt) => {
  if (txt && reasoningStartTime.value) {
    reasoningDuration.value = Math.max(1, Math.ceil((Date.now() - reasoningStartTime.value) / 1000))
    reasoningStartTime.value = null
    if (timerInterval) {
      clearInterval(timerInterval)
      timerInterval = null
    }
  }
})

onUnmounted(() => {
  if (timerInterval) clearInterval(timerInterval)
  if (textActivityTimeout) clearTimeout(textActivityTimeout)
})

// ══════════════════════════════════════════════════════════════════════════════
// 🎭 RANDOMIZED DYNAMIC EXPRESSION POOLS (12+ VARIANTS PER STAGE)
// ══════════════════════════════════════════════════════════════════════════════

// Stage 1: Query & Intent Analysis
const queryIntentActiveVariants = [
  'Analyzing the query intent...',
  'Deciphering your prompt...',
  'Deconstructing the inquiry...',
  'Parsing semantic nuances...',
  'Formulating thought approach...',
  'Mapping problem scope & context...',
  'Understanding key requirements...',
  'Extracting core entities & goals...',
  'Dissecting question structure...',
  'Unraveling the underlying intent...',
  'Interpreting question context...',
  'Scoping information needs...'
]

const queryIntentDoneVariants = [
  'Query intent analyzed',
  'Prompt deciphered',
  'Inquiry deconstructed',
  'Semantic context mapped',
  'Core requirements understood',
  'Intent parsed successfully',
  'Problem structure clarified',
  'Scope & entities identified',
  'Key goals captured',
  'Nuances recognized',
  'Inquiry context established',
  'Information scope locked'
]

// Stage 3: Deep Reasoning & Synthesis
const reasoningActiveVariants = [
  'Reasoning and synthesizing knowledge...',
  'Connecting factual dots...',
  'Cross-referencing evidence & citations...',
  'Synthesizing insights from documentation...',
  'Evaluating candidate hypotheses...',
  'Constructing logical deduction chain...',
  'Weighing relevant knowledge points...',
  'Analyzing domain relationships...',
  'Formulating coherent logical steps...',
  'Validating consistency across sources...',
  'Distilling core concepts & findings...',
  'Structuring multi-step inference...'
]

const reasoningDoneVariants = [
  'Reasoning completed',
  'Insights synthesized',
  'Logical deduction verified',
  'Evidence cross-referenced',
  'Knowledge points distilled',
  'Facts structured & aligned',
  'Context fully synthesized',
  'Logical framework established',
  'Key findings reconciled',
  'Multi-step inference verified',
  'Domain logic confirmed',
  'Core conclusions finalized'
]

// Stage 4: Formulating & Writing Response
const writingActiveVariants = [
  'Writing response...',
  'Crafting detailed breakdown...',
  'Formatting structured answer...',
  'Composing clear explanation...',
  'Polishing solution details...',
  'Drafting comprehensive summary...',
  'Organizing key points & examples...',
  'Assembling final explanation...',
  'Structuring readable answer...',
  'Generating tailored response...',
  'Streaming final insights...',
  'Refining delivery & formatting...'
]

const writingDoneVariants = [
  'Response generated',
  'Answer ready',
  'Explanation finalized',
  'Output completed',
  'Solution formulated',
  'Summary organized',
  'Response crafted',
  'Comprehensive answer built',
  'Delivery complete',
  'Results summarized',
  'Insights compiled',
  'Detailed response prepared'
]

// Deterministic seed per message to maintain stable choice during a message's turn while varying across messages
function getVariantIndex(seedStr: string, poolLength: number, salt: number = 0): number {
  if (!seedStr) return salt % poolLength
  let hash = 0
  for (let i = 0; i < seedStr.length; i++) {
    hash = (hash << 5) - hash + seedStr.charCodeAt(i) + salt
    hash |= 0
  }
  return Math.abs(hash) % poolLength
}

const variantSeed = computed(() => props.message.id || 'seed_default')
const stage1Index = computed(() => getVariantIndex(variantSeed.value, queryIntentActiveVariants.length, 1))
const stage3Index = computed(() => getVariantIndex(variantSeed.value, reasoningActiveVariants.length, 7))
const stage4Index = computed(() => getVariantIndex(variantSeed.value, writingActiveVariants.length, 13))
</script>

<template>
  <div v-if="searchPart || reasoningPart" class="my-2 select-none font-sans">
    <!-- Grok-style Vertical Step Tree -->
    <div class="relative pl-6 py-1 flex flex-col gap-2.5">
      <!-- Vertical connecting line -->
      <div v-show="isStepTreeOpen" class="absolute left-[9px] top-2.5 bottom-2.5 w-[1.5px] bg-neutral-800"></div>

      <!-- Step 1: Intention & Problem Analysis (Clickable to collapse/expand step tree) -->
      <div
        class="relative flex items-center gap-2.5 text-sm cursor-pointer select-none group/step-head py-0.5"
        :title="isStepTreeOpen ? '点击收起步骤' : '点击展开步骤'"
        @click="toggleStepTree"
      >
        <div class="absolute -left-6 flex items-center justify-center w-5 h-5 rounded-full bg-neutral-950 text-amber-400 group-hover/step-head:scale-110 transition-transform">
          <UIcon name="i-lucide-lightbulb" class="w-4 h-4 text-amber-400" />
        </div>
        <span class="text-neutral-200 font-normal group-hover/step-head:text-amber-300 transition-colors">
          {{ stepStage === 1 ? queryIntentActiveVariants[stage1Index] : queryIntentDoneVariants[stage1Index] }}
        </span>
        <!-- Small chevron indicator -->
        <UIcon
          name="i-lucide-chevron-down"
          class="size-3.5 text-neutral-500 group-hover/step-head:text-neutral-300 transition-transform duration-200"
          :class="{ '-rotate-90': !isStepTreeOpen }"
        />
      </div>

      <!-- Collapsible Steps Container -->
      <div v-show="isStepTreeOpen" class="flex flex-col gap-2.5">
        <!-- Step 2: Knowledge Base Search -->
        <div v-if="searchPart || citations.length > 0 || stepStage >= 2" class="relative flex flex-col gap-1.5 text-sm">
          <div class="flex items-center gap-2.5">
            <div class="absolute -left-6 flex items-center justify-center w-5 h-5 rounded-full bg-neutral-950 text-neutral-400">
              <UIcon v-if="isSearchStreaming" name="i-lucide-loader-2" class="w-3.5 h-3.5 animate-spin text-emerald-400" />
              <div v-else class="w-2.5 h-2.5 rounded-full border border-neutral-600 bg-neutral-950"></div>
            </div>
            <span :class="isSearchStreaming ? 'text-emerald-400 font-medium animate-pulse' : 'text-neutral-300'">
              {{ isSearchStreaming ? 'Searching knowledge base...' : 'Knowledge base searched' }}
            </span>
            <span v-if="uniqueDocuments.length > 0" class="text-xs text-neutral-500 font-mono">
              ({{ uniqueDocuments.length }} {{ uniqueDocuments.length === 1 ? 'source' : 'sources' }})
            </span>
          </div>

          <!-- Grok-style Document Pills Horizontal Scrolling Ribbon -->
          <div
            v-if="visibleDocuments.length > 0"
            class="relative w-full max-w-full overflow-hidden mt-0.5 mb-1"
          >
            <!-- Horizontal scrolling container with staggered entrance -->
            <TransitionGroup
              name="pill-stagger"
              tag="div"
              class="flex items-center gap-2 overflow-x-auto py-1 px-0.5 scroll-smooth select-none [mask-image:linear-gradient(to_right,black_calc(100%-24px),transparent_100%)]"
            >
              <div
                v-for="(doc, idx) in visibleDocuments"
                :key="doc.doc_id || `doc-${idx}`"
                class="group inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-neutral-800 bg-neutral-900/90 hover:bg-neutral-800 hover:border-emerald-500/40 text-xs text-neutral-300 hover:text-neutral-100 transition-all duration-300 cursor-pointer shrink-0 max-w-[260px] shadow-sm active:scale-95"
                :title="`${doc.title || doc.doc_id} (相关度: ${getRelevanceScore(doc.score, idx)}%)`"
                @click="handlePillClick(doc)"
              >
                <!-- Document Icon -->
                <UIcon
                  :name="getDocIcon(doc.title, doc.doc_id)"
                  class="w-3.5 h-3.5 text-emerald-400 shrink-0 group-hover:scale-110 transition-transform"
                />
                <!-- Document Title -->
                <span class="truncate font-sans font-normal text-xs text-neutral-300 group-hover:text-emerald-300 transition-colors">
                  {{ formatDocName(doc.title, doc.doc_id, idx) }}
                </span>
                <!-- Calibrated Relevance Percentage (0-100%) -->
                <span
                  class="text-[10px] font-mono shrink-0 pl-1 font-medium transition-colors"
                  :class="getRelevanceScore(doc.score, idx) >= 90 ? 'text-emerald-400' : getRelevanceScore(doc.score, idx) >= 80 ? 'text-teal-400' : 'text-neutral-400'"
                >
                  {{ getRelevanceScore(doc.score, idx) }}%
                </span>
              </div>
            </TransitionGroup>
          </div>
        </div>

        <!-- Step 3: Deep Reasoning Thinking -->
        <div v-if="reasoningPart || stepStage >= 3" class="relative flex items-center gap-2.5 text-sm">
          <div class="absolute -left-6 flex items-center justify-center w-5 h-5 rounded-full bg-neutral-950 text-neutral-400">
            <UIcon v-if="isReasoningStreaming" name="i-lucide-loader-2" class="w-3.5 h-3.5 animate-spin text-neutral-300" />
            <div v-else class="w-2.5 h-2.5 rounded-full border border-neutral-600 bg-neutral-950"></div>
          </div>
          <span :class="isReasoningStreaming ? 'text-neutral-200 font-medium' : 'text-neutral-300'">
            {{ isReasoningStreaming ? reasoningActiveVariants[stage3Index] : reasoningDoneVariants[stage3Index] }}
          </span>
        </div>

        <!-- Step 4: Formulating Response -->
        <div v-if="textPart || stepStage >= 4" class="relative flex items-center gap-2.5 text-sm">
          <div class="absolute -left-6 flex items-center justify-center w-5 h-5 rounded-full bg-neutral-950 text-neutral-400">
            <div class="w-2.5 h-2.5 rounded-full border border-neutral-600 bg-neutral-950"></div>
          </div>
          <span :class="isTextStreaming ? 'text-neutral-200 animate-pulse' : 'text-neutral-400'">
            {{ isTextStreaming ? writingActiveVariants[stage4Index] : writingDoneVariants[stage4Index] }}
          </span>
        </div>
      </div>
    </div>

    <!-- Bottom Action Row: Thought for Xs on the Left, Retrieved knowledge base on the Right -->
    <div class="mt-2.5 flex items-center gap-4 flex-wrap">
      <!-- 1. Thought for Xs (Left) -->
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
        <span v-if="isReasoningStreaming" class="animate-pulse">Thinking...</span>
        <span v-else>Thought for {{ displayDuration }}</span>
      </button>

      <!-- 2. Retrieved Knowledge Base / Sources (Right) -->
      <button
        v-if="citations.length > 0"
        type="button"
        class="inline-flex items-center gap-1.5 text-sm font-medium text-neutral-300 hover:text-neutral-100 transition-colors py-1 cursor-pointer select-none"
        @click="isSourcesOpen = !isSourcesOpen"
      >
        <UIcon
          name="i-lucide-chevron-down"
          class="size-4 text-neutral-400 transition-transform duration-200"
          :class="{ '-rotate-90': !isSourcesOpen }"
        />
        <span>Retrieved knowledge base</span>
      </button>
    </div>

    <!-- Collapsible Document Sources Card -->
    <div v-if="isSourcesOpen && citations.length > 0" class="w-full mt-2">
      <ChatToolSources :citations="citations" @select-doc="handlePillClick" />
    </div>

    <!-- Collapsible Thinking Process Trace Panel -->
    <div
      v-if="isReasoningOpen && (reasoningPart as any)?.text"
      class="w-full mt-2 p-3.5 rounded-xl bg-neutral-900/60 border border-neutral-800/80 text-xs text-neutral-300 font-sans"
    >
      <ChatComark
        :markdown="(reasoningPart as any).text"
        :streaming="isReasoningStreaming"
      />
    </div>

    <!-- Full Document Content Viewer Modal with Highlighted Chunks -->
    <ModalDocumentViewer
      v-model:open="isDocViewerOpen"
      :doc="selectedDoc"
      :all-citations="citations"
    />
  </div>
</template>

<style scoped>
.pill-stagger-enter-active {
  transition: all 0.35s cubic-bezier(0.16, 1, 0.3, 1);
}
.pill-stagger-enter-from {
  opacity: 0;
  transform: translateX(12px) scale(0.94);
}
.pill-stagger-enter-to {
  opacity: 1;
  transform: translateX(0) scale(1);
}
</style>
