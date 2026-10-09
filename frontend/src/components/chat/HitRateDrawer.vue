<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import type { UIMessage } from 'ai'
import { $fetch } from 'ofetch'
import { formatRetrievalScore } from '../../utils/evidence'

interface ChunkCitation {
  doc_id: string
  chunk_id?: string
  title: string
  score?: number
  similarity?: number
  snippet?: string
  space?: string
  index?: number
}

const props = withDefaults(defineProps<{
  open: boolean
  messages: UIMessage[]
  totalDocs?: number
}>(), {
  totalDocs: undefined
})

const emit = defineEmits<{
  (e: 'update:open', val: boolean): void
}>()

const systemDocTotal = ref<number | undefined>(props.totalDocs)

onMounted(async () => {
  try {
    const res: any = await $fetch('/api/metrics')
    if (Array.isArray(res?.indexedDocs)) {
      systemDocTotal.value = res.indexedDocs.length
    }
  } catch (e) {
    // Unknown values must remain unknown.
  }
})

// Preserve actual retrieval scores; never turn rank into a quality percentage.
function rawRetrievalScore(item: any): number | undefined {
  return typeof item.score === 'number' && Number.isFinite(item.score) ? item.score : undefined
}

// Helper to extract tool output citations returned from assistant message parts
function getCitationsFromMessage(m: UIMessage): ChunkCitation[] {
  if (!m.parts) return []

  const citations: ChunkCitation[] = []
  const seenIds = new Set<string>()

  for (const part of m.parts) {
    if (!part || part.type !== 'tool-rag_search') continue
    const output = (part as any).output || (part as any).result || (part as any).data
    if (output) {
      const arr = Array.isArray(output) ? output : [output]
      let idx = 0
      for (const item of arr) {
        if (item && typeof item === 'object' && (item.doc_id || item.docId || item.title || item.chunk_id)) {
          const chunkId = item.chunk_id || item.chunkId || item.doc_id || item.title
          if (!seenIds.has(chunkId)) {
            seenIds.add(chunkId)
            idx++
            const itemIdx = item.index ?? idx
            const sim = rawRetrievalScore(item)

            citations.push({
              index: itemIdx,
              doc_id: item.doc_id || item.docId || chunkId,
              chunk_id: chunkId,
              title: item.title || item.doc_id || `Chunk #${itemIdx}`,
              score: rawRetrievalScore(item),
              similarity: sim,
              snippet: item.snippet || item.chunk_text || item.text || '',
              space: item.space || null
            })
          }
        }
      }
    }
  }

  return citations
}

// Compute per-turn Hit Rate & Similarity metrics (chronological order)
const questionTurns = computed(() => {
  const turns: {
    turnIndex: number
    userQuery: string
    citations: ChunkCitation[]
    retrievedCount: number
    isHit: boolean
    hitRatePercent: number
    topSimilarity?: number
    avgSimilarity?: number
    isPending?: boolean
  }[] = []

  let currentTurnUser: UIMessage | undefined = undefined
  let turnCount = 0

  for (const m of props.messages) {
    if (m.role === 'user') {
      currentTurnUser = m
    } else if (m.role === 'assistant') {
      turnCount++
      let qText = ''
      if (currentTurnUser) {
        if ((currentTurnUser as UIMessage & { content?: string }).content) {
          qText = (currentTurnUser as UIMessage & { content?: string }).content ?? ""
        } else if (currentTurnUser.parts) {
          for (const p of currentTurnUser.parts) {
            if ((p.type === 'text' || p.type === 'reasoning') && (p as any).text) {
              qText = (p as any).text
              break
            }
          }
        }
      }
      qText = qText.trim().replace(/\s+/g, ' ') || `Question #${turnCount}`

      const citations = getCitationsFromMessage(m)
      const retrievedCount = citations.length
      const isHit = retrievedCount > 0
      const hitRatePercent = isHit ? 100 : 0

      let topSimilarity: number | undefined
      let totalSimSum = 0
      let simCount = 0

      for (const c of citations) {
        const val = c.similarity
        if (typeof val === 'number') {
          if (topSimilarity === undefined || val > topSimilarity) topSimilarity = val
          totalSimSum += val
          simCount++
        }
      }

      const avgSimilarity = simCount > 0 ? totalSimSum / simCount : undefined

      turns.push({
        turnIndex: turnCount,
        userQuery: qText,
        citations,
        retrievedCount,
        isHit,
        hitRatePercent,
        topSimilarity,
        avgSimilarity,
        isPending: false
      })

      currentTurnUser = undefined
    }
  }

  // Handle pending new user message during streaming
  if (currentTurnUser) {
    turnCount++
    let qText = (currentTurnUser as UIMessage & { content?: string }).content ?? ''
    if (!qText && currentTurnUser.parts) {
      for (const p of currentTurnUser.parts) {
        if ((p.type === 'text' || p.type === 'reasoning') && (p as any).text) {
          qText = (p as any).text
          break
        }
      }
    }
    qText = qText.trim().replace(/\s+/g, ' ') || `Question #${turnCount}`

    turns.push({
      turnIndex: turnCount,
      userQuery: qText,
      citations: [],
      retrievedCount: 0,
      isHit: false,
      hitRatePercent: 0,
      topSimilarity: undefined,
      avgSimilarity: undefined,
      isPending: true
    })
  }

  return turns
})

// Sorted question turns: Latest question turn appears at the VERY TOP
const sortedQuestionTurns = computed(() => {
  return [...questionTurns.value].reverse()
})

// Overall conversation-level Hit Rate & Similarity metrics
const overallMetrics = computed(() => {
  const completedTurns = questionTurns.value.filter(t => !t.isPending || t.citations.length > 0)
  const hitTurnsCount = completedTurns.filter(t => t.isHit).length
  const totalTurns = completedTurns.length

  let totalRetrievedChunks = 0
  let overallTopSim: number | undefined
  let totalSimSum = 0
  let simCount = 0
  const uniqueDocIds = new Set<string>()

  for (const turn of completedTurns) {
    totalRetrievedChunks += turn.retrievedCount
    for (const c of turn.citations) {
      if (c.doc_id) uniqueDocIds.add(c.doc_id)
      const val = c.similarity
      if (typeof val === 'number') {
        if (overallTopSim === undefined || val > overallTopSim) overallTopSim = val
        totalSimSum += val
        simCount++
      }
    }
  }

  const hitRatePercent = totalTurns > 0
    ? Number(((hitTurnsCount / totalTurns) * 100).toFixed(1))
    : 0

  const avgSimilarity = simCount > 0 ? totalSimSum / simCount : undefined

  return {
    totalSystemDocs: systemDocTotal.value,
    recalledUniqueDocsCount: uniqueDocIds.size,
    totalRetrievedChunks,
    hitTurnsCount,
    totalTurns,
    hitRatePercent,
    topSimilarity: overallTopSim,
    avgSimilarity
  }
})

function closeDrawer() {
  emit('update:open', false)
}
</script>

<template>
  <Transition name="panel">
    <div
      v-if="open"
      class="h-full w-80 sm:w-[400px] border-l border-zinc-800/90 bg-zinc-950/95 dark:bg-zinc-900/95 flex flex-col shrink-0 relative z-20 shadow-2xl transition-all duration-300"
    >
      <!-- Header -->
      <div class="p-4 border-b border-zinc-800/80 flex items-center justify-between shrink-0">
        <div class="flex items-center gap-2">
          <div class="p-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
            <UIcon name="i-lucide-bar-chart-3" class="w-4 h-4" />
          </div>
          <div>
            <h3 class="text-xs font-semibold text-zinc-100">回答引用与检索记录</h3>
          </div>
        </div>
        <button
          type="button"
          aria-label="关闭检索记录"
          class="p-1.5 rounded-lg text-zinc-400 hover:text-white hover:bg-zinc-800 transition-colors cursor-pointer"
          @click="closeDrawer"
        >
          <UIcon name="i-lucide-x" class="w-4 h-4" />
        </button>
      </div>

      <!-- Content Scrollable Body -->
      <div class="flex-1 overflow-y-auto p-4 space-y-4">

        <!-- Card 1: Overall Hit Rate Card -->
        <div class="p-3.5 bg-gradient-to-br from-zinc-900/90 to-zinc-950 border border-zinc-800 rounded-2xl space-y-3 shadow-sm">
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium text-zinc-400 uppercase tracking-wider">有引用的回答比例</span>
            <UBadge :color="overallMetrics.hitRatePercent >= 60 ? 'success' : 'info'" variant="subtle" size="xs">
              {{ overallMetrics.hitRatePercent }}% 有引用
            </UBadge>
          </div>

          <!-- Main Metric Big Stat -->
          <div class="flex items-baseline justify-between pt-1">
            <div class="space-y-0.5">
              <div class="text-2xl font-bold font-mono text-emerald-400 flex items-baseline gap-1">
                <span>{{ overallMetrics.hitTurnsCount }}</span>
                <span class="text-xs font-normal text-zinc-500">/ {{ overallMetrics.totalTurns }} 轮有引用</span>
              </div>
              <p class="text-[11px] text-zinc-400">仅统计返回引用，不代表召回率、相关性或回答正确率。</p>
            </div>
            <div class="text-right font-mono">
              <div class="text-xs text-zinc-400">核心切块</div>
              <div class="text-base font-bold text-emerald-400">{{ overallMetrics.totalRetrievedChunks }} 个</div>
            </div>
          </div>

          <!-- Progress Bar -->
          <div class="space-y-1 pt-1">
            <div class="h-2 w-full bg-zinc-800 rounded-full overflow-hidden flex">
              <div
                class="h-full bg-gradient-to-r from-emerald-500 to-teal-400 rounded-full transition-all duration-500"
                :style="{ width: `${overallMetrics.hitRatePercent}%` }"
              ></div>
            </div>
          </div>
        </div>

        <!-- Card 2: Similarity Metrics Card -->
        <div class="p-3.5 bg-gradient-to-br from-sky-950/20 via-zinc-900/90 to-zinc-950 border border-sky-500/20 rounded-2xl space-y-3 shadow-sm">
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium text-sky-400 uppercase tracking-wider flex items-center gap-1">
              <UIcon name="i-lucide-sparkles" class="w-3.5 h-3.5 text-sky-400" />
              返回的检索分（非置信度）
            </span>
          </div>

          <!-- Similarity Numbers Grid -->
          <div class="grid grid-cols-2 gap-2 pt-1 font-mono text-center">
            <div class="p-2 bg-zinc-950/80 rounded-xl border border-sky-500/20">
              <div class="text-[10px] text-zinc-500">平均返回分</div>
              <div class="text-lg font-bold text-sky-400">{{ formatRetrievalScore(overallMetrics.avgSimilarity) }}</div>
            </div>
            <div class="p-2 bg-zinc-950/80 rounded-xl border border-emerald-500/20">
              <div class="text-[10px] text-zinc-500">最高返回分</div>
              <div class="text-lg font-bold text-emerald-400">{{ formatRetrievalScore(overallMetrics.topSimilarity) }}</div>
            </div>
          </div>
          <p class="text-[11px] text-zinc-500">不同检索算法和查询的分值不可直接比较；不做语义质量判定。</p>
        </div>

        <!-- System Capacity Mini Grid -->
        <div class="grid grid-cols-2 gap-2 text-xs font-mono">
          <div class="p-2.5 bg-zinc-900/60 rounded-xl border border-zinc-800">
            <div class="text-[10px] text-zinc-500">知识库总文档数</div>
            <div class="font-bold text-zinc-200 mt-0.5">{{ overallMetrics.totalSystemDocs ?? '未知' }} 篇文档</div>
          </div>
          <div class="p-2.5 bg-zinc-900/60 rounded-xl border border-zinc-800">
            <div class="text-[10px] text-zinc-500">返回引用涉及文档</div>
            <div class="font-bold text-emerald-400 mt-0.5">{{ overallMetrics.recalledUniqueDocsCount }} 篇</div>
          </div>
        </div>

        <!-- Question Turn Breakdown Header -->
        <div class="flex items-center justify-between pt-1">
          <h4 class="text-xs font-semibold text-zinc-300 uppercase tracking-wider flex items-center gap-1.5">
            <UIcon name="i-lucide-list-ordered" class="w-3.5 h-3.5 text-emerald-400" />
            按提问逐项分析 (最新置顶)
          </h4>
          <span class="text-[10px] text-zinc-500 font-mono">共 {{ sortedQuestionTurns.length }} 轮</span>
        </div>

        <!-- Empty State -->
        <div v-if="!sortedQuestionTurns.length" class="text-center py-10 text-xs text-zinc-500 italic">
          暂无提问召回数据
        </div>

        <!-- Turn Cards List (Ultra Concise & Latest Turn First) -->
        <div v-else class="space-y-2.5">
          <div
            v-for="turn in sortedQuestionTurns"
            :key="turn.turnIndex"
            class="p-3 bg-zinc-900/60 border border-zinc-800/80 rounded-xl space-y-2 hover:border-zinc-700 transition-colors"
          >
            <!-- Turn Title & Hit Rate Badge -->
            <div class="flex items-start justify-between gap-2">
              <div class="flex items-start gap-2 min-w-0">
                <span class="w-4 h-4 rounded-full bg-emerald-500/20 border border-emerald-500/30 text-emerald-400 text-[10px] font-mono font-bold flex items-center justify-center shrink-0 mt-0.5">
                  {{ turn.turnIndex }}
                </span>
                <span class="text-xs font-medium text-zinc-200 line-clamp-2" :title="turn.userQuery">
                  {{ turn.userQuery }}
                </span>
              </div>

              <!-- Hit Rate Badge -->
              <div class="shrink-0 text-right font-mono">
                <div v-if="turn.isPending" class="px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/20 text-amber-400 text-[10px] font-bold flex items-center gap-1">
                  <UIcon name="i-lucide-loader-2" class="w-3 h-3 animate-spin" />
                  <span>分析中</span>
                </div>
                <div v-else :class="['px-2 py-0.5 rounded border text-[10px] font-bold', turn.isHit ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' : 'bg-zinc-800 border-zinc-700 text-zinc-400']">
                  {{ turn.isHit ? '有引用' : '无引用' }}
                </div>
              </div>
            </div>

            <!-- Ultra-Concise Summary Line: Avg Similarity & Retrieved Count -->
            <div v-if="!turn.isPending" class="flex items-center justify-between text-[11px] pt-1.5 border-t border-zinc-800/60 font-mono">
              <span class="text-zinc-400 flex items-center gap-1">
                <span>平均检索分:</span>
                <strong class="text-sky-400 font-bold">{{ formatRetrievalScore(turn.avgSimilarity) }}</strong>
              </span>
              <span class="text-zinc-500 text-[10px]">
                {{ turn.retrievedCount > 0 ? `返回 ${turn.retrievedCount} 个引用片段` : '未返回引用片段' }}
              </span>
            </div>
            <div v-else class="text-[10px] text-amber-400/80 italic pt-1.5 border-t border-zinc-800/60 flex items-center gap-1.5">
              <UIcon name="i-lucide-refresh-cw" class="w-3 h-3 animate-spin" />
              <span>正在等待回答引用...</span>
            </div>
          </div>
        </div>

      </div>
    </div>
  </Transition>
</template>

<style scoped>
.panel-enter-active,
.panel-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}
.panel-enter-from,
.panel-leave-to {
  opacity: 0;
  transform: translateX(100%);
}
</style>
