<script setup lang="ts">
import { ref, computed, onMounted, useId } from 'vue'
import { isToolUIPart, getToolName, type UIMessage } from 'ai'
import { $fetch } from 'ofetch'

interface ChunkCitation {
  doc_id: string
  chunk_id: string
  title: string
  similarity?: number
  snippet: string
}

const props = defineProps<{ open: boolean; messages: UIMessage[]; totalDocs?: number }>()
const emit = defineEmits<{ (e: 'update:open', val: boolean): void }>()
const panelId = useId()
const systemDocTotal = ref<number>()
const expandedTurnIndex = ref<number | null>(null)
const activeFilter = ref<'all' | 'hit' | 'direct'>('all')

onMounted(async () => {
  try {
    const res = await $fetch<{ indexedDocs?: unknown[] }>('/api/metrics')
    if (Array.isArray(res.indexedDocs)) systemDocTotal.value = res.indexedDocs.length
  } catch {
    // Metrics are administrator-only. Unavailable counts remain unknown.
  }
})

// Only explicit cosine values are comparable; hybrid/reranker scores are not cosine.
function cosinePercent(item: Record<string, unknown>): number | undefined {
  const value = item.similarity ?? item.vector_score ?? item.vectorScore
  if (typeof value !== 'number' || !Number.isFinite(value) || value < -1 || value > 1) return undefined
  return Math.round(value * 100)
}

function getCitationsFromMessage(message: UIMessage): ChunkCitation[] {
  const citations: ChunkCitation[] = []
  const seen = new Set<string>()
  for (const part of message.parts ?? []) {
    if (!isToolUIPart(part) || getToolName(part) !== 'rag_search' || !Array.isArray(part.output)) continue
    for (const item of part.output) {
      if (!item || typeof item !== 'object' || typeof item.doc_id !== 'string') continue
      const chunkId = String(item.chunk_id ?? item.doc_id)
      const key = [item.source_type ?? 'knowledge', item.doc_id, chunkId].join(':')
      if (seen.has(key)) continue
      seen.add(key)
      citations.push({
        doc_id: [item.source_type ?? 'knowledge', item.doc_id].join(':'),
        chunk_id: key,
        title: item.title || item.doc_id,
        similarity: cosinePercent(item),
        snippet: item.snippet || item.chunk_text || ''
      })
    }
  }
  return citations
}

function average(values: number[]): number | undefined {
  return values.length ? Math.round(values.reduce((sum, value) => sum + value, 0) / values.length) : undefined
}

const questionTurns = computed(() => {
  let turnIndex = 0
  return props.messages.flatMap((message, index) => {
    if (message.role !== 'user') return []
    turnIndex++
    const assistant = props.messages[index + 1]?.role === 'assistant' ? props.messages[index + 1] : undefined
    const citations = assistant ? getCitationsFromMessage(assistant) : []
    const similarities = citations.flatMap(citation => citation.similarity === undefined ? [] : [citation.similarity])
    return [{
      turnIndex,
      userQuery: message.parts.filter(part => part.type === 'text').map(part => part.text).join(' ').trim() || 'Turn ' + turnIndex,
      citations,
      isHit: citations.length > 0,
      isPending: !assistant || !assistant.parts.some(part =>
        (part.type === 'text' && part.text.trim().length > 0) ||
        (isToolUIPart(part) && part.state === 'output-available')
      ),
      avgSimilarity: average(similarities)
    }]
  })
})

const filters = computed(() => [
  { value: 'all' as const, label: 'All', count: questionTurns.value.length },
  { value: 'hit' as const, label: 'Cited', count: questionTurns.value.filter(turn => turn.isHit).length },
  { value: 'direct' as const, label: 'Uncited', count: questionTurns.value.filter(turn => !turn.isHit && !turn.isPending).length }
])
const filteredQuestionTurns = computed(() => [...questionTurns.value].reverse().filter(turn => {
  if (activeFilter.value === 'hit') return turn.isHit
  if (activeFilter.value === 'direct') return !turn.isHit && !turn.isPending
  return true
}))
const overallMetrics = computed(() => {
  const turns = questionTurns.value.filter(turn => !turn.isPending)
  const hitTurnsCount = turns.filter(turn => turn.isHit).length
  const citations = turns.flatMap(turn => turn.citations)
  const similarities = citations.flatMap(citation => citation.similarity === undefined ? [] : [citation.similarity])
  return {
    totalTurns: turns.length,
    hitTurnsCount,
    hitRatePercent: turns.length ? Math.round(hitTurnsCount / turns.length * 100) : 0,
    totalChunks: citations.length,
    citedDocs: new Set(citations.map(citation => citation.doc_id)).size,
    avgSimilarity: average(similarities),
    topSimilarity: similarities.length ? Math.max(...similarities) : undefined,
    totalSystemDocs: systemDocTotal.value ?? props.totalDocs
  }
})
function formatSimilarity(value: number | undefined) {
  return value === undefined ? '—' : value + '%'
}
function toggleTurn(index: number) {
  expandedTurnIndex.value = expandedTurnIndex.value === index ? null : index
}
</script>

<template>
  <Transition name="panel">
    <aside v-if="open" lang="en" class="analytics-panel" :aria-labelledby="panelId + '-title'">
      <header class="panel-header">
        <div class="header-icon"><UIcon name="i-lucide-chart-no-axes-combined" class="size-5" /></div>
        <div class="header-copy">
          <p class="eyebrow">RETRIEVAL ANALYTICS</p>
          <h2 :id="panelId + '-title'">Retrieval monitor</h2>
        </div>
        <button type="button" class="icon-button" aria-label="Close retrieval monitor" @click="emit('update:open', false)">
          <UIcon name="i-lucide-x" class="size-4" />
        </button>
      </header>
      <div class="panel-body">
        <section class="overview-card" aria-label="Conversation citation overview">
          <div class="section-heading">
            <span class="metric-label">Citation coverage</span>
            <span class="session-badge"><span class="status-dot" />Current chat</span>
          </div>
          <div class="hero-metric">
            <span class="hero-value">{{ overallMetrics.totalTurns ? overallMetrics.hitRatePercent : '—' }}</span>
            <span v-if="overallMetrics.totalTurns" class="hero-unit">%</span>
            <div class="hero-side-stat"><strong>{{ overallMetrics.totalChunks }}</strong><span>Cited chunks</span></div>
          </div>
          <p v-if="overallMetrics.totalTurns" class="metric-caption"><strong>{{ overallMetrics.hitTurnsCount }}</strong> / {{ overallMetrics.totalTurns }} answers include knowledge citations</p>
          <p v-else class="metric-caption">Citation coverage appears after the first answer.</p>
          <div class="progress-track" role="progressbar" aria-label="Citation coverage" :aria-valuenow="overallMetrics.hitRatePercent" :aria-valuemin="0" :aria-valuemax="100">
            <div class="progress-fill" :style="{ width: overallMetrics.hitRatePercent + '%' }" />
          </div>
          <div class="overview-footnote"><span>Returned answers only</span><span>{{ overallMetrics.totalTurns }} turns</span></div>
        </section>
        <section class="similarity-section" aria-label="Vector similarity">
          <div class="section-heading"><h3>Vector similarity</h3><span class="section-meta">Cosine</span></div>
          <div class="similarity-grid">
            <div class="similarity-cell">
              <span class="metric-label"><UIcon name="i-lucide-scan-line" class="size-3.5" />Average similarity</span>
              <strong>{{ formatSimilarity(overallMetrics.avgSimilarity) }}</strong>
              <span class="cell-caption">Across scored chunks</span>
            </div>
            <div class="similarity-cell">
              <span class="metric-label"><UIcon name="i-lucide-arrow-up-right" class="size-3.5" />Top similarity</span>
              <strong>{{ formatSimilarity(overallMetrics.topSimilarity) }}</strong>
              <span class="cell-caption">Best recorded match</span>
            </div>
          </div>
          <p v-if="overallMetrics.avgSimilarity === undefined" class="section-note">No vector scores recorded. Citations are still available.</p>
        </section>
        <dl class="footprint">
          <div><dt>Indexed docs</dt><dd>{{ overallMetrics.totalSystemDocs ?? '—' }}</dd></div>
          <div><dt>Cited docs</dt><dd>{{ overallMetrics.citedDocs }}</dd></div>
          <div><dt>Questions</dt><dd>{{ questionTurns.length }}</dd></div>
        </dl>
        <section class="trace-section" aria-label="Turn history">
          <div class="section-heading"><h3>Turn history</h3><span class="section-meta">Latest first</span></div>
          <div class="filter-group" role="group" aria-label="Filter citation records">
            <button v-for="filter in filters" :key="filter.value" type="button" :aria-pressed="activeFilter === filter.value" :class="{ active: activeFilter === filter.value }" @click="activeFilter = filter.value">
              {{ filter.label }}<span>{{ filter.count }}</span>
            </button>
          </div>
          <div v-if="!filteredQuestionTurns.length" class="empty-state">
            <div class="empty-icon"><UIcon name="i-lucide-chart-no-axes-column" class="size-5" /></div>
            <strong>{{ questionTurns.length ? 'No matching turns' : 'Ready for your first question' }}</strong>
            <p>{{ questionTurns.length ? 'Try another filter to explore your answers.' : 'Ask a question to explore citations and matching details.' }}</p>
          </div>
          <div v-else class="turn-list">
            <article v-for="turn in filteredQuestionTurns" :key="turn.turnIndex" class="turn-card" :class="{ expanded: expandedTurnIndex === turn.turnIndex }">
              <button type="button" class="turn-trigger" :aria-expanded="expandedTurnIndex === turn.turnIndex" :aria-controls="panelId + '-turn-' + turn.turnIndex" @click="toggleTurn(turn.turnIndex)">
                <span class="turn-number">{{ String(turn.turnIndex).padStart(2, '0') }}</span>
                <span class="turn-copy">
                  <span class="turn-title" :title="turn.userQuery">{{ turn.userQuery }}</span>
                  <span class="turn-caption">
                    <template v-if="turn.isHit">{{ turn.citations.length }} cited chunks<span v-if="turn.avgSimilarity !== undefined"> · {{ turn.avgSimilarity }}% similarity</span></template>
                    <template v-else>{{ turn.isPending ? 'Waiting for a response' : 'No knowledge citations' }}</template>
                  </span>
                </span>
                <span class="turn-status" :class="{ hit: turn.isHit, pending: turn.isPending }">
                  <UIcon v-if="turn.isPending" name="i-lucide-loader-circle" class="size-3 animate-spin" />
                  {{ turn.isPending ? 'Pending' : turn.isHit ? 'Cited' : 'Uncited' }}
                </span>
                <UIcon name="i-lucide-chevron-down" class="turn-chevron size-3.5" />
              </button>
              <div v-if="expandedTurnIndex === turn.turnIndex" :id="panelId + '-turn-' + turn.turnIndex" class="turn-detail">
                <template v-if="turn.citations.length">
                  <div class="detail-heading"><span>Cited chunks · {{ turn.citations.length }}</span><span>Similarity</span></div>
                  <div v-for="citation in turn.citations" :key="citation.chunk_id" class="citation-card">
                    <div class="citation-heading"><UIcon name="i-lucide-file-text" class="size-3.5" /><span :title="citation.title">{{ citation.title }}</span><strong>{{ formatSimilarity(citation.similarity) }}</strong></div>
                    <p v-if="citation.snippet">{{ citation.snippet }}</p>
                  </div>
                </template>
                <p v-else class="detail-note">{{ turn.isPending ? 'Citation details will appear when the answer returns.' : 'This answer has no knowledge citations to display.' }}</p>
              </div>
            </article>
          </div>
        </section>
      </div>
      <footer class="panel-footer"><UIcon name="i-lucide-info" class="size-3.5" /><span>Citation records for this conversation</span><span class="footer-brand">AI-QA</span></footer>
    </aside>
  </Transition>
</template>

<style scoped>
.analytics-panel {
  --panel-accent: var(--ui-primary);
  --panel-tint: color-mix(in srgb, var(--panel-accent) 6%, var(--ui-bg));
  display: flex; flex-direction: column; flex-shrink: 0;
  width: 420px; max-width: 100%; height: 100%; min-height: 0; overflow: hidden;
  border-left: 1px solid var(--ui-border); background: var(--ui-bg); color: var(--ui-text);
  font-size: 12px; line-height: 1.5;
}
.panel-header { display: flex; align-items: center; gap: 12px; padding: 22px 24px; border-bottom: 1px solid var(--ui-border); }
.header-icon { display: grid; place-items: center; width: 40px; height: 40px; border: 1px solid color-mix(in srgb, var(--panel-accent) 15%, var(--ui-border)); border-radius: 12px; color: var(--panel-accent); background: var(--panel-tint); }
.header-copy { flex: 1; min-width: 0; }
.eyebrow { margin: 0 0 3px; font-size: 9px; font-weight: 600; letter-spacing: 0.14em; color: var(--ui-text-muted); }
h2 { margin: 0; font-size: 17px; font-weight: 650; letter-spacing: -0.02em; color: var(--ui-text-highlighted); }
.icon-button { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 8px; color: var(--ui-text-muted); cursor: pointer; }
.icon-button:hover { color: var(--ui-text-highlighted); background: var(--ui-bg-elevated); }
button:focus-visible { outline: 2px solid var(--panel-accent); outline-offset: 3px; }
.panel-body { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 24px; }
.overview-card { padding: 20px; border: 1px solid color-mix(in srgb, var(--panel-accent) 14%, var(--ui-border)); border-radius: 16px; background: linear-gradient(130deg, var(--panel-tint), var(--ui-bg)); }
.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.metric-label { display: inline-flex; align-items: center; gap: 6px; color: var(--ui-text-toned); font-size: 11px; font-weight: 500; }
.session-badge { display: inline-flex; align-items: center; gap: 5px; font-size: 10px; color: var(--ui-text-muted); }
.status-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--panel-accent); }
.hero-metric { display: flex; align-items: baseline; margin-top: 18px; gap: 3px; color: var(--ui-text-highlighted); }
.hero-value { font-size: 48px; line-height: 1.1; font-weight: 600; letter-spacing: -0.06em; font-variant-numeric: tabular-nums; }
.hero-unit { font-size: 23px; color: var(--ui-text-muted); font-weight: 400; }
.hero-side-stat { margin-left: auto; display: flex; flex-direction: column; text-align: right; gap: 2px; }
.hero-side-stat strong { font-size: 24px; font-weight: 550; line-height: 1.2; font-variant-numeric: tabular-nums; }
.hero-side-stat span { font-size: 10px; color: var(--ui-text-muted); }
.metric-caption { margin: 10px 0 18px; color: var(--ui-text-muted); font-size: 11px; }
.metric-caption strong { font-weight: 600; color: var(--ui-text-toned); }
.progress-track { height: 5px; background: var(--ui-bg-accented); border-radius: 4px; overflow: hidden; }
.progress-fill { height: 100%; background: var(--panel-accent); border-radius: inherit; transition: width 0.4s ease; }
.overview-footnote { display: flex; justify-content: space-between; margin-top: 9px; font-size: 9px; color: var(--ui-text-muted); }
.similarity-section { margin-top: 24px; }
h3 { font-size: 12px; font-weight: 600; color: var(--ui-text-highlighted); margin: 0; }
.section-meta { font-size: 10px; color: var(--ui-text-muted); }
.similarity-grid { margin-top: 12px; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border: 1px solid var(--ui-border); border-radius: 12px; background: var(--ui-bg); }
.similarity-cell { display: flex; flex-direction: column; padding: 16px; gap: 7px; }
.similarity-cell + .similarity-cell { border-left: 1px solid var(--ui-border); }
.similarity-cell strong { font-size: 25px; line-height: 1.2; font-weight: 550; color: var(--ui-text-highlighted); font-variant-numeric: tabular-nums; letter-spacing: -0.04em; }
.cell-caption { font-size: 9px; color: var(--ui-text-muted); }
.section-note { font-size: 10px; margin: 9px 0 0; color: var(--ui-text-muted); }
.footprint { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); padding: 17px 0; margin: 20px 0 26px; border-top: 1px solid var(--ui-border); border-bottom: 1px solid var(--ui-border); }
.footprint > div { text-align: center; }
.footprint > div + div { border-left: 1px solid var(--ui-border); }
.footprint dt { font-size: 10px; color: var(--ui-text-muted); }
.footprint dd { margin: 6px 0 0; font-size: 17px; font-weight: 600; color: var(--ui-text-highlighted); font-variant-numeric: tabular-nums; }
.filter-group { display: flex; padding: 3px; margin: 12px 0 14px; border-radius: 10px; background: var(--ui-bg-muted); border: 1px solid var(--ui-border); }
.filter-group button { display: flex; justify-content: center; align-items: center; gap: 7px; flex: 1; padding: 6px 0; border-radius: 7px; cursor: pointer; color: var(--ui-text-muted); font-size: 11px; transition: background 0.15s, color 0.15s; }
.filter-group button:hover { color: var(--ui-text-highlighted); }
.filter-group button.active { background: var(--ui-bg); color: var(--ui-text-highlighted); box-shadow: 0 1px 3px rgb(0 0 0 / 7%); font-weight: 600; }
.filter-group button span { font-size: 10px; font-variant-numeric: tabular-nums; color: var(--ui-text-muted); }
.turn-list { display: flex; flex-direction: column; gap: 8px; }
.turn-card { border: 1px solid var(--ui-border); border-radius: 12px; overflow: hidden; transition: border-color 0.15s; }
.turn-card:hover, .turn-card.expanded { border-color: var(--ui-border-accented); }
.turn-trigger { display: flex; align-items: center; gap: 10px; width: 100%; padding: 14px 12px; text-align: left; cursor: pointer; }
.turn-trigger:hover { background: var(--ui-bg-muted); }
.turn-number { flex-shrink: 0; color: var(--ui-text-muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.turn-copy { display: flex; flex-direction: column; flex: 1; min-width: 0; gap: 4px; }
.turn-title { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; color: var(--ui-text-highlighted); font-size: 12px; font-weight: 550; }
.turn-caption { font-size: 10px; color: var(--ui-text-muted); }
.turn-status { display: inline-flex; align-items: center; gap: 4px; flex-shrink: 0; padding: 3px 6px; font-size: 9px; border-radius: 5px; background: var(--ui-bg-elevated); color: var(--ui-text-muted); }
.turn-status.hit { background: var(--panel-tint); color: var(--panel-accent); }
.turn-status.pending { color: var(--ui-warning); background: color-mix(in srgb, var(--ui-warning) 10%, var(--ui-bg)); }
.turn-chevron { color: var(--ui-text-muted); flex-shrink: 0; transition: transform 0.2s; }
.expanded .turn-chevron { transform: rotate(180deg); }
.turn-detail { padding: 12px; border-top: 1px solid var(--ui-border); background: var(--ui-bg-muted); }
.detail-heading { display: flex; justify-content: space-between; font-size: 9px; color: var(--ui-text-muted); margin-bottom: 9px; }
.citation-card { padding: 11px; border-radius: 8px; background: var(--ui-bg); border: 1px solid var(--ui-border); }
.citation-card + .citation-card { margin-top: 8px; }
.citation-heading { display: flex; align-items: center; gap: 6px; color: var(--panel-accent); }
.citation-heading > span { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; color: var(--ui-text-highlighted); }
.citation-heading strong { font-size: 11px; font-weight: 600; font-variant-numeric: tabular-nums; }
.citation-card p { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; margin: 8px 0 0; font-size: 11px; line-height: 1.7; color: var(--ui-text-muted); overflow-wrap: anywhere; }
.detail-note { margin: 0; font-size: 11px; line-height: 1.8; color: var(--ui-text-muted); }
.empty-state { display: flex; flex-direction: column; align-items: center; text-align: center; padding: 30px 16px; border: 1px dashed var(--ui-border); border-radius: 12px; }
.empty-icon { display: grid; place-items: center; width: 38px; height: 38px; border-radius: 12px; color: var(--ui-text-muted); background: var(--ui-bg-muted); margin-bottom: 12px; }
.empty-state strong { font-size: 12px; font-weight: 500; color: var(--ui-text-toned); }
.empty-state p { font-size: 11px; line-height: 1.8; color: var(--ui-text-muted); margin: 6px 0 0; max-width: 240px; }
.panel-footer { display: flex; align-items: center; gap: 6px; padding: 14px 24px; border-top: 1px solid var(--ui-border); color: var(--ui-text-muted); font-size: 10px; }
.footer-brand { margin-left: auto; font-size: 9px; letter-spacing: 0.1em; }
.panel-enter-active, .panel-leave-active { transition: opacity 0.2s ease, transform 0.2s ease; }
.panel-enter-from, .panel-leave-to { opacity: 0; transform: translateX(24px); }
/* Keep secondary copy readable in a narrow panel. */
.metric-label, h3 { font-size: 12px; }
.session-badge, .hero-side-stat span, .overview-footnote, .section-meta, .cell-caption,
.section-note, .footprint dt, .turn-caption, .detail-heading, .panel-footer { font-size: 11px; }
.turn-status { font-size: 10px; }
.turn-trigger:focus-visible { outline-offset: -3px; }
@media (max-width: 767px) {
  .analytics-panel { position: absolute; inset: 0 0 0 auto; width: min(400px, 100%); z-index: 30; box-shadow: -12px 0 32px rgb(0 0 0 / 8%); }
}
@media (max-width: 380px) {
  .panel-header { padding: 18px 16px; }
  .panel-body { padding: 18px 16px; }
  .panel-footer { padding: 12px 16px; }
  .turn-trigger { gap: 7px; }
}
@media (prefers-reduced-motion: reduce) {
  .analytics-panel *, .panel-enter-active, .panel-leave-active { transition: none; animation: none; }
}
</style>
