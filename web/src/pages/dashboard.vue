<route lang="yaml">
meta:
  layout: false
</route>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { $fetch } from 'ofetch'
import { useRouter } from 'vue-router'

const router = useRouter()
const loading = ref(false)
const autoRefresh = ref(true)
const lastUpdated = ref<string>('')
let timer: ReturnType<typeof setInterval> | null = null

const metricsData = ref<any>({
  uptime: 0,
  services: {
    agentApi: 'unknown',
    webServer: 'healthy',
    vectorDb: 'unknown',
    database: 'healthy',
  },
  counts: {
    topics: 0,
    documents: 0,
  },
  requests: {
    total: 0,
    p50: 0,
    p95: 0,
    p99: 0,
    byEndpoint: {},
  },
  db: {
    totalQueries: 0,
    totalDurationMs: 0,
    avgMs: 0,
    slowQueries: 0,
  },
  ai: {
    totalCalls: 0,
    totalDurationMs: 0,
    avgMs: 0,
    totalTokens: 0,
    ttftP50: 0,
    ttftP95: 0,
    ttftP99: 0,
  },
})

async function fetchMetrics() {
  loading.value = true
  try {
    const res = await $fetch('/api/metrics')
    metricsData.value = res
    lastUpdated.value = new Date().toLocaleTimeString()
  } catch (e) {
    console.error('Failed to load metrics:', e)
  } finally {
    loading.value = false
  }
}

function formatUptime(seconds: number): string {
  if (!seconds || seconds <= 0) return '0s'
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60

  const parts = []
  if (d > 0) parts.push(`${d}d`)
  if (h > 0) parts.push(`${h}h`)
  if (m > 0) parts.push(`${m}m`)
  parts.push(`${s}s`)
  return parts.join(' ')
}

function startTimer() {
  stopTimer()
  if (autoRefresh.value) {
    timer = setInterval(fetchMetrics, 3000)
  }
}

function stopTimer() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

watch(autoRefresh, (val) => {
  if (val) startTimer()
  else stopTimer()
})

onMounted(() => {
  fetchMetrics()
  startTimer()
})

onUnmounted(() => {
  stopTimer()
})

const endpointList = computed(() => {
  const byEp = metricsData.value?.requests?.byEndpoint || {}
  return Object.entries(byEp).map(([key, data]: [string, any]) => {
    const [method, ...pathParts] = key.split(' ')
    return {
      key,
      method,
      path: pathParts.join(' '),
      count: data.count || 0,
      avgMs: data.avgMs || 0,
      p50: data.p50 || 0,
      p95: data.p95 || 0,
      statusCodes: data.statusCodes || {},
    }
  }).sort((a, b) => b.count - a.count)
})

const indexedDocList = computed(() => {
  return metricsData.value?.indexedDocs || []
})

function formatDate(dateStr: string): string {
  if (!dateStr) return '-'
  try {
    const d = new Date(dateStr)
    if (isNaN(d.getTime())) return dateStr
    return d.toLocaleDateString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    })
  } catch (e) {
    return dateStr
  }
}

function getStatusBadge(status: string) {
  if (status === 'healthy') return { color: 'success', label: 'Healthy' }
  if (status === 'degraded') return { color: 'warning', label: 'Degraded' }
  if (status === 'offline') return { color: 'error', label: 'Offline' }
  return { color: 'neutral', label: status || 'Active' }
}
</script>

<template>
  <div class="min-h-screen bg-zinc-950 text-zinc-100 p-4 sm:p-8 space-y-6 max-w-7xl mx-auto">
    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-6 border-b border-zinc-800">
      <div class="flex items-center gap-3">
        <div class="p-3 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
          <UIcon name="i-lucide-layout-dashboard" class="w-8 h-8" />
        </div>
        <div>
          <h1 class="text-2xl font-bold text-zinc-100 tracking-tight flex items-center gap-2.5">
            系统运行与实时监控 Dashboard
            <span class="inline-flex items-center gap-1.5 text-xs px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 font-mono border border-emerald-500/20">
              <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
              Live Sync
            </span>
          </h1>
          <p class="text-xs text-zinc-400 mt-0.5">系统核心指标、服务存活状态、LLM 调用与接口性能全局视图</p>
        </div>
      </div>

      <div class="flex items-center gap-3 self-end sm:self-auto">
        <div class="flex items-center gap-2 bg-zinc-900 border border-zinc-800 px-3.5 py-2 rounded-xl text-xs">
          <span class="text-zinc-400">自动刷新 (3s):</span>
          <USwitch v-model="autoRefresh" size="xs" color="emerald" />
        </div>
        <UButton
          color="neutral"
          variant="outline"
          icon="i-lucide-refresh-cw"
          size="sm"
          :class="['rounded-xl text-zinc-300 hover:text-white', loading ? 'animate-spin text-emerald-400' : '']"
          label="刷新"
          @click="fetchMetrics"
        />
        <UButton
          color="neutral"
          variant="ghost"
          icon="i-lucide-arrow-left"
          size="sm"
          class="rounded-xl text-zinc-400 hover:text-white"
          label="返回对话"
          @click="router.push('/')"
        />
      </div>
    </div>

    <!-- Top Stat Cards (4 Columns) -->
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <!-- Card 1: System Uptime -->
      <div class="bg-zinc-900/80 border border-zinc-800/80 rounded-2xl p-5 space-y-2 relative overflow-hidden group hover:border-zinc-700 transition-colors">
        <div class="flex items-center justify-between text-xs text-zinc-400">
          <span>系统已连续运行</span>
          <UIcon name="i-lucide-clock" class="w-4 h-4 text-emerald-400" />
        </div>
        <div class="text-3xl font-bold font-mono text-emerald-400">
          {{ formatUptime(metricsData?.uptime) }}
        </div>
        <div class="text-[11px] text-zinc-500 flex items-center gap-1.5 pt-1">
          <UIcon name="i-lucide-check-circle" class="w-3.5 h-3.5 text-emerald-500" />
          Web / Agent 服务在线
        </div>
      </div>

      <!-- Card 2: HTTP Requests & Latency -->
      <div class="bg-zinc-900/80 border border-zinc-800/80 rounded-2xl p-5 space-y-2 relative overflow-hidden group hover:border-zinc-700 transition-colors">
        <div class="flex items-center justify-between text-xs text-zinc-400">
          <span>总 HTTP 请求量</span>
          <UIcon name="i-lucide-arrow-left-right" class="w-4 h-4 text-sky-400" />
        </div>
        <div class="text-3xl font-bold font-mono text-zinc-100 flex items-baseline gap-2">
          {{ metricsData?.requests?.total || 0 }}
          <span class="text-xs font-normal text-zinc-400">请求</span>
        </div>
        <div class="text-[11px] text-zinc-400 font-mono flex items-center gap-2 pt-1">
          <span>P50: {{ metricsData?.requests?.p50 || 0 }}ms</span>
          <span class="text-zinc-600">•</span>
          <span>P95: {{ metricsData?.requests?.p95 || 0 }}ms</span>
        </div>
      </div>

      <!-- Card 3: AI / LLM Calls & Tokens -->
      <div class="bg-zinc-900/80 border border-zinc-800/80 rounded-2xl p-5 space-y-2 relative overflow-hidden group hover:border-zinc-700 transition-colors">
        <div class="flex items-center justify-between text-xs text-zinc-400">
          <span>AI 调用与 Token 消耗</span>
          <UIcon name="i-lucide-sparkles" class="w-4 h-4 text-purple-400" />
        </div>
        <div class="text-3xl font-bold font-mono text-purple-400 flex items-baseline gap-2">
          {{ metricsData?.ai?.totalCalls || 0 }}
          <span class="text-xs font-normal text-zinc-400">Calls / {{ metricsData?.ai?.totalTokens || 0 }} Tokens</span>
        </div>
        <div class="text-[11px] text-zinc-400 font-mono pt-1">
          TTFT P50: {{ metricsData?.ai?.ttftP50 || 0 }}ms
        </div>
      </div>

      <!-- Card 4: Knowledge & DB Queries -->
      <div class="bg-zinc-900/80 border border-zinc-800/80 rounded-2xl p-5 space-y-2 relative overflow-hidden group hover:border-zinc-700 transition-colors">
        <div class="flex items-center justify-between text-xs text-zinc-400">
          <span>知识库与数据库统计</span>
          <UIcon name="i-lucide-database" class="w-4 h-4 text-amber-400" />
        </div>
        <div class="text-3xl font-bold font-mono text-zinc-100 flex items-baseline gap-2">
          {{ metricsData?.counts?.topics || 0 }}
          <span class="text-xs font-normal text-zinc-400">Topics / {{ metricsData?.counts?.documents || 0 }} Docs</span>
        </div>
        <div class="text-[11px] text-zinc-400 font-mono flex items-center justify-between pt-1">
          <span>DB Queries: {{ metricsData?.db?.totalQueries || 0 }}</span>
          <span v-if="metricsData?.db?.slowQueries > 0" class="text-amber-400">Slow: {{ metricsData?.db?.slowQueries }}</span>
        </div>
      </div>
    </div>

    <!-- Service Matrix Status -->
    <div class="bg-zinc-900/60 border border-zinc-800 rounded-2xl p-5 space-y-4">
      <h3 class="text-xs font-semibold text-zinc-400 uppercase tracking-wider flex items-center gap-2">
        <UIcon name="i-lucide-server" class="w-4 h-4 text-emerald-400" />
        核心服务状态矩阵 (Service Matrix Status)
      </h3>
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <!-- Agent Python API -->
        <div class="p-4 bg-zinc-950 rounded-xl border border-zinc-800/80 flex items-center justify-between">
          <div class="space-y-1">
            <div class="text-xs font-semibold text-zinc-200">Agent API Service</div>
            <div class="text-[11px] text-zinc-500 font-mono">Port 8000 (FastAPI)</div>
          </div>
          <UBadge :color="getStatusBadge(metricsData?.services?.agentApi).color" variant="subtle" size="sm" class="capitalize">
            {{ getStatusBadge(metricsData?.services?.agentApi).label }}
          </UBadge>
        </div>

        <!-- Nitro Web Server -->
        <div class="p-4 bg-zinc-950 rounded-xl border border-zinc-800/80 flex items-center justify-between">
          <div class="space-y-1">
            <div class="text-xs font-semibold text-zinc-200">Nitro Web Server</div>
            <div class="text-[11px] text-zinc-500 font-mono">Port 3000 (Nuxt/Vite)</div>
          </div>
          <UBadge color="success" variant="subtle" size="sm">
            Healthy
          </UBadge>
        </div>

        <!-- Vector Backend -->
        <div class="p-4 bg-zinc-950 rounded-xl border border-zinc-800/80 flex items-center justify-between">
          <div class="space-y-1">
            <div class="text-xs font-semibold text-zinc-200">Vector Engine</div>
            <div class="text-[11px] font-mono text-zinc-500 uppercase">{{ metricsData?.services?.vectorDb || 'milvus' }}</div>
          </div>
          <UBadge color="info" variant="subtle" size="sm">
            Active
          </UBadge>
        </div>

        <!-- SQLite DB -->
        <div class="p-4 bg-zinc-950 rounded-xl border border-zinc-800/80 flex items-center justify-between">
          <div class="space-y-1">
            <div class="text-xs font-semibold text-zinc-200">SQLite Database</div>
            <div class="text-[11px] text-zinc-500 font-mono">LibSQL / Drizzle</div>
          </div>
          <UBadge color="success" variant="subtle" size="sm">
            Connected
          </UBadge>
        </div>
      </div>
    </div>

    <!-- Latency & Endpoint Activity Grid -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <!-- Latency Quantiles -->
      <div class="bg-zinc-900/60 border border-zinc-800 rounded-2xl p-5 space-y-5">
        <h3 class="text-xs font-semibold text-zinc-400 uppercase tracking-wider flex items-center gap-2">
          <UIcon name="i-lucide-activity" class="w-4 h-4 text-sky-400" />
          响应延迟分布监控 (Latency Quantiles)
        </h3>

        <!-- HTTP Quantiles -->
        <div class="space-y-3">
          <div class="text-xs text-zinc-300 font-medium">全局 HTTP 响应耗时 (P50 / P95 / P99)</div>
          <div class="grid grid-cols-3 gap-3 text-center font-mono">
            <div class="p-3 bg-zinc-950 rounded-xl border border-zinc-800">
              <div class="text-[11px] text-zinc-500">P50 (中位数)</div>
              <div class="text-xl font-bold text-emerald-400">{{ metricsData?.requests?.p50 || 0 }}<span class="text-xs font-normal">ms</span></div>
            </div>
            <div class="p-3 bg-zinc-950 rounded-xl border border-zinc-800">
              <div class="text-[11px] text-zinc-500">P95 (95%分位)</div>
              <div class="text-xl font-bold text-amber-400">{{ metricsData?.requests?.p95 || 0 }}<span class="text-xs font-normal">ms</span></div>
            </div>
            <div class="p-3 bg-zinc-950 rounded-xl border border-zinc-800">
              <div class="text-[11px] text-zinc-500">P99 (长尾峰值)</div>
              <div class="text-xl font-bold text-rose-400">{{ metricsData?.requests?.p99 || 0 }}<span class="text-xs font-normal">ms</span></div>
            </div>
          </div>
        </div>

        <!-- AI TTFT Quantiles -->
        <div class="space-y-3 pt-3 border-t border-zinc-800/80">
          <div class="text-xs text-zinc-300 font-medium">AI 流式首字延迟 TTFT (Time to First Token)</div>
          <div class="grid grid-cols-3 gap-3 text-center font-mono">
            <div class="p-3 bg-zinc-950 rounded-xl border border-zinc-800">
              <div class="text-[11px] text-zinc-500">TTFT P50</div>
              <div class="text-xl font-bold text-purple-400">{{ metricsData?.ai?.ttftP50 || 0 }}<span class="text-xs font-normal">ms</span></div>
            </div>
            <div class="p-3 bg-zinc-950 rounded-xl border border-zinc-800">
              <div class="text-[11px] text-zinc-500">TTFT P95</div>
              <div class="text-xl font-bold text-purple-300">{{ metricsData?.ai?.ttftP95 || 0 }}<span class="text-xs font-normal">ms</span></div>
            </div>
            <div class="p-3 bg-zinc-950 rounded-xl border border-zinc-800">
              <div class="text-[11px] text-zinc-500">TTFT P99</div>
              <div class="text-xl font-bold text-purple-200">{{ metricsData?.ai?.ttftP99 || 0 }}<span class="text-xs font-normal">ms</span></div>
            </div>
          </div>
        </div>
      </div>

      <!-- Indexed Documents Monitoring List (长条卡片列表，可滑动) -->
      <div class="bg-zinc-900/60 border border-zinc-800 rounded-2xl p-5 space-y-4">
        <div class="flex items-center justify-between">
          <h3 class="text-xs font-semibold text-zinc-400 uppercase tracking-wider flex items-center gap-2">
            <UIcon name="i-lucide-file-text" class="w-4 h-4 text-emerald-400" />
            已入库文档监控列表 (INDEXED DOCUMENTS)
          </h3>
          <span class="text-[11px] text-zinc-500 font-mono">共 {{ indexedDocList.length }} 篇已入库文档</span>
        </div>

        <div v-if="!indexedDocList.length" class="text-center py-12 text-xs text-zinc-500 italic">
          暂无已入库文档数据
        </div>

        <!-- Scrollable List of Long Cards -->
        <div v-else class="space-y-2.5 max-h-80 overflow-y-auto pr-1">
          <div
            v-for="doc in indexedDocList"
            :key="doc.doc_id"
            class="flex items-center justify-between p-3.5 bg-zinc-950 rounded-xl border border-zinc-800/80 hover:border-zinc-700 transition-all group"
          >
            <!-- Left: Icon + Title + Space Tag -->
            <div class="flex items-center gap-3 min-w-0 pr-3">
              <div class="p-2 rounded-lg bg-zinc-900 border border-zinc-800 text-emerald-400 shrink-0">
                <UIcon name="i-lucide-file-text" class="w-4 h-4" />
              </div>
              <div class="min-w-0">
                <div class="text-xs font-medium text-zinc-200 truncate group-hover:text-emerald-300 transition-colors">
                  {{ doc.title || doc.doc_id }}
                </div>
                <div v-if="doc.space" class="text-[11px] text-zinc-500 flex items-center gap-2 pt-0.5">
                  <span class="text-[10px] px-1.5 py-0.2 rounded bg-zinc-900 border border-zinc-800 text-zinc-400 font-mono">
                    {{ doc.space }}
                  </span>
                </div>
              </div>
            </div>

            <!-- Right: Last Updated Time & Character Count -->
            <div class="flex items-center gap-4 text-xs font-mono shrink-0">
              <!-- Last Updated -->
              <div class="text-right text-zinc-400 text-[11px] flex items-center gap-1.5">
                <UIcon name="i-lucide-calendar" class="w-3.5 h-3.5 text-zinc-500" />
                <span>{{ formatDate(doc.last_updated) }}</span>
              </div>

              <!-- Word Count Badge -->
              <div class="px-2.5 py-1 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 font-bold text-xs flex items-center gap-1">
                <span>{{ doc.char_count?.toLocaleString() || 0 }}</span>
                <span class="text-[10px] font-normal text-emerald-500">字</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Footer Info -->
    <div class="pt-4 text-center text-xs text-zinc-500 flex items-center justify-between border-t border-zinc-800/80">
      <span>上次更新: {{ lastUpdated || 'Just now' }}</span>
      <span>SCUT-Elite-Camp AI-QA-Assistant Metrics Engine</span>
    </div>
  </div>
</template>
