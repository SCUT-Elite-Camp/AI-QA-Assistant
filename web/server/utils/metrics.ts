/**
 * 轻量级内存 Metrics 采集器。
 * 无外部依赖，纯内存计数器 + 延迟直方图。
 */

interface LatencyBucket {
  count: number
  totalMs: number
  min: number
  max: number
  // 用于近似 P50/P95/P99
  samples: number[]
}

interface EndpointMetrics {
  count: number
  statusCodes: Record<number, number>
  latency: LatencyBucket
}

interface MetricsStore {
  startTime: number
  requests: {
    total: number
    byEndpoint: Record<string, EndpointMetrics>
  }
  db: {
    totalQueries: number
    totalDurationMs: number
    slowQueries: number // > 100ms
  }
  ai: {
    totalCalls: number
    totalDurationMs: number
    totalTokens: number
    ttftBuckets: LatencyBucket
  }
  memory: {
    compaction: Record<string, number>
    durations: Record<string, LatencyBucket>
    fact: Record<string, number>
    fallback: Record<string, number>
    resolve: Record<string, number>
  }
}

function createLatencyBucket(): LatencyBucket {
  return {
    count: 0,
    totalMs: 0,
    min: Infinity,
    max: 0,
    samples: [],
  }
}

function recordLatency(bucket: LatencyBucket, ms: number) {
  bucket.count++
  bucket.totalMs += ms
  bucket.min = Math.min(bucket.min, ms)
  bucket.max = Math.max(bucket.max, ms)
  // 保留最近 1000 个样本用于分位数计算
  bucket.samples.push(ms)
  if (bucket.samples.length > 1000) {
    bucket.samples.shift()
  }
}

function calcPercentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0
  const idx = Math.ceil((p / 100) * sorted.length) - 1
  return sorted[Math.max(0, Math.min(idx, sorted.length - 1))] ?? 0
}

const store: MetricsStore = {
  startTime: Date.now(),
  requests: {
    total: 0,
    byEndpoint: {},
  },
  db: {
    totalQueries: 0,
    totalDurationMs: 0,
    slowQueries: 0,
  },
  ai: {
    totalCalls: 0,
    totalDurationMs: 0,
    totalTokens: 0,
    ttftBuckets: createLatencyBucket(),
  },
  memory: {
    compaction: {},
    durations: {},
    fact: {},
    fallback: {},
    resolve: {}
  }
}

const MEMORY_RESOLVE_SOURCES = new Set(['disabled', 'trusted_context', 'legacy'])
const MEMORY_RESOLVE_OUTCOMES = new Set(['success', 'fallback', 'rejected'])
const MEMORY_COMPACTION_OUTCOMES = new Set(['skipped', 'planned', 'conflict', 'failed'])
const MEMORY_FACT_ACTIONS = new Set(['proposed', 'suppressed', 'recalled'])
const MEMORY_FACT_OUTCOMES = new Set(['success', 'disabled', 'sensitive', 'empty', 'failed'])
const MEMORY_FALLBACK_REASONS = new Set(['agent_disabled', 'internal_error', 'context_error'])
const MEMORY_DURATION_OPERATIONS = new Set(['context', 'internal_chat', 'compaction'])

function incrementMemoryCounter (counter: Record<string, number>, label: string) {
  counter[label] = (counter[label] ?? 0) + 1
}

function recordMemoryDurationBucket (operation: string, durationMs: number) {
  if (!MEMORY_DURATION_OPERATIONS.has(operation) || !Number.isFinite(durationMs) || durationMs < 0) return
  store.memory.durations[operation] ??= createLatencyBucket()
  recordLatency(store.memory.durations[operation]!, durationMs)
}

export function recordMemoryResolve (source: string, outcome: string) {
  if (!MEMORY_RESOLVE_SOURCES.has(source) || !MEMORY_RESOLVE_OUTCOMES.has(outcome)) return
  incrementMemoryCounter(store.memory.resolve, `${source}:${outcome}`)
}

export function recordMemoryCompaction (outcome: string) {
  if (!MEMORY_COMPACTION_OUTCOMES.has(outcome)) return
  incrementMemoryCounter(store.memory.compaction, outcome)
}

export function recordMemoryFact (action: string, outcome: string) {
  if (!MEMORY_FACT_ACTIONS.has(action) || !MEMORY_FACT_OUTCOMES.has(outcome)) return
  incrementMemoryCounter(store.memory.fact, `${action}:${outcome}`)
}

export function recordMemoryFallback (reason: string) {
  if (!MEMORY_FALLBACK_REASONS.has(reason)) return
  incrementMemoryCounter(store.memory.fallback, reason)
}

export function recordMemoryDuration (operation: string, durationMs: number) {
  recordMemoryDurationBucket(operation, durationMs)
}

function getOrCreateEndpoint(method: string, path: string): EndpointMetrics {
  const key = `${method} ${path}`
  if (!store.requests.byEndpoint[key]) {
    store.requests.byEndpoint[key] = {
      count: 0,
      statusCodes: {},
      latency: createLatencyBucket(),
    }
  }
  return store.requests.byEndpoint[key]!
}

// ==================== 公开 API ====================

/** 记录一次 HTTP 请求 */
export function recordRequest(method: string, path: string, statusCode: number, durationMs: number) {
  store.requests.total++
  const ep = getOrCreateEndpoint(method, path)
  ep.count++
  ep.statusCodes[statusCode] = (ep.statusCodes[statusCode] || 0) + 1
  recordLatency(ep.latency, durationMs)
}

/** 记录一次数据库查询 */
export function recordDbQuery(durationMs: number) {
  store.db.totalQueries++
  store.db.totalDurationMs += durationMs
  if (durationMs > 100) {
    store.db.slowQueries++
  }
}

/** 记录一次 AI 模型调用 */
export function recordAiCall(durationMs: number, ttftMs: number, tokens: number) {
  store.ai.totalCalls++
  store.ai.totalDurationMs += durationMs
  store.ai.totalTokens += tokens
  recordLatency(store.ai.ttftBuckets, ttftMs)
}

/** 获取当前 Metrics 快照 */
export function getMetrics() {
  const uptime = Date.now() - store.startTime

  // 计算全局延迟分布
  const allLatencies: number[] = []
  for (const ep of Object.values(store.requests.byEndpoint)) {
    allLatencies.push(...ep.latency.samples)
  }
  allLatencies.sort((a, b) => a - b)

  const aiSamples = [...store.ai.ttftBuckets.samples].sort((a, b) => a - b)

  return {
    uptime: Math.round(uptime / 1000),
    requests: {
      total: store.requests.total,
      p50: calcPercentile(allLatencies, 50),
      p95: calcPercentile(allLatencies, 95),
      p99: calcPercentile(allLatencies, 99),
      byEndpoint: Object.fromEntries(
        Object.entries(store.requests.byEndpoint).map(([key, ep]) => {
          const sorted = [...ep.latency.samples].sort((a, b) => a - b)
          return [key, {
            count: ep.count,
            avgMs: ep.latency.count > 0 ? Math.round(ep.latency.totalMs / ep.latency.count) : 0,
            p50: calcPercentile(sorted, 50),
            p95: calcPercentile(sorted, 95),
            p99: calcPercentile(sorted, 99),
            statusCodes: ep.statusCodes,
          }]
        }),
      ),
    },
    db: {
      totalQueries: store.db.totalQueries,
      totalDurationMs: Math.round(store.db.totalDurationMs),
      avgMs: store.db.totalQueries > 0 ? Math.round(store.db.totalDurationMs / store.db.totalQueries) : 0,
      slowQueries: store.db.slowQueries,
    },
    ai: {
      totalCalls: store.ai.totalCalls,
      totalDurationMs: Math.round(store.ai.totalDurationMs),
      avgMs: store.ai.totalCalls > 0 ? Math.round(store.ai.totalDurationMs / store.ai.totalCalls) : 0,
      totalTokens: store.ai.totalTokens,
      ttftP50: calcPercentile(aiSamples, 50),
      ttftP95: calcPercentile(aiSamples, 95),
      ttftP99: calcPercentile(aiSamples, 99),
    },
    memory: {
      compaction: { ...store.memory.compaction },
      durations: Object.fromEntries(Object.entries(store.memory.durations).map(([operation, bucket]) => [operation, {
        count: bucket.count,
        totalMs: Math.round(bucket.totalMs),
        avgMs: bucket.count > 0 ? Math.round(bucket.totalMs / bucket.count) : 0
      }])),
      fact: { ...store.memory.fact },
      fallback: { ...store.memory.fallback },
      resolve: { ...store.memory.resolve }
    }
  }
}

// ==================== Prometheus 格式导出 ====================

/** 辅助：转义 Prometheus label 值中的特殊字符 */
function escapeLabelValue(v: string): string {
  return v.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\n/g, '\\n')
}

/** 将内部 Metrics 转换为 Prometheus 文本格式 */
export function getPrometheusMetrics(): string {
  const now = Date.now()
  const uptime = (now - store.startTime) / 1000
  const lines: string[] = []

  // --- 帮助信息 ---
  lines.push('# HELP http_requests_total Total number of HTTP requests.')
  lines.push('# TYPE http_requests_total counter')
  lines.push(`http_requests_total ${store.requests.total}`)

  lines.push('# HELP http_request_duration_ms HTTP request latency in milliseconds.')
  lines.push('# TYPE http_request_duration_ms histogram')

  // 按端点 + 状态码输出指标
  for (const [key, ep] of Object.entries(store.requests.byEndpoint)) {
    const [method, path] = key.split(' ')
    const labels = `method="${escapeLabelValue(method)}",path="${escapeLabelValue(path)}"`
    lines.push(`http_requests_total{${labels}} ${ep.count}`)

    if (ep.latency.count > 0) {
      const sorted = [...ep.latency.samples].sort((a, b) => a - b)
      const avg = Math.round(ep.latency.totalMs / ep.latency.count)
      lines.push(`http_request_duration_ms_sum{${labels}} ${ep.latency.totalMs}`)
      lines.push(`http_request_duration_ms_count{${labels}} ${ep.latency.count}`)
      lines.push(`http_request_duration_ms_avg{${labels}} ${avg}`)
      lines.push(`http_request_duration_ms_p50{${labels}} ${calcPercentile(sorted, 50)}`)
      lines.push(`http_request_duration_ms_p95{${labels}} ${calcPercentile(sorted, 95)}`)
      lines.push(`http_request_duration_ms_p99{${labels}} ${calcPercentile(sorted, 99)}`)
    }

    // 按状态码
    for (const [code, count] of Object.entries(ep.statusCodes)) {
      lines.push(`http_requests_total{${labels},status_code="${code}"} ${count}`)
    }
  }

  // --- 全局延迟 ---
  const allLatencies: number[] = []
  for (const ep of Object.values(store.requests.byEndpoint)) {
    allLatencies.push(...ep.latency.samples)
  }
  allLatencies.sort((a, b) => a - b)

  lines.push('# HELP http_request_duration_overall_ms Overall HTTP request latency percentiles.')
  lines.push('# TYPE http_request_duration_overall_ms summary')
  lines.push(`http_request_duration_overall_ms{quantile="0.50"} ${calcPercentile(allLatencies, 50)}`)
  lines.push(`http_request_duration_overall_ms{quantile="0.95"} ${calcPercentile(allLatencies, 95)}`)
  lines.push(`http_request_duration_overall_ms{quantile="0.99"} ${calcPercentile(allLatencies, 99)}`)

  // --- 错误率 ---
  let totalErrors = 0
  for (const ep of Object.values(store.requests.byEndpoint)) {
    for (const [code, count] of Object.entries(ep.statusCodes)) {
      if (Number(code) >= 400) totalErrors += count
    }
  }
  lines.push('# HELP http_errors_total Total HTTP error responses (4xx, 5xx).')
  lines.push('# TYPE http_errors_total counter')
  lines.push(`http_errors_total ${totalErrors}`)

  // --- 吞吐量 (req/s 近似) ---
  if (uptime > 0) {
    const throughput = store.requests.total / uptime
    lines.push('# HELP http_throughput_requests_per_second Approximate requests per second.')
    lines.push('# TYPE http_throughput_requests_per_second gauge')
    lines.push(`http_throughput_requests_per_second ${throughput.toFixed(4)}`)
  }

  // --- DB 指标 ---
  lines.push('# HELP db_queries_total Total database queries.')
  lines.push('# TYPE db_queries_total counter')
  lines.push(`db_queries_total ${store.db.totalQueries}`)

  lines.push('# HELP db_query_duration_ms_total Total database query duration in ms.')
  lines.push('# TYPE db_query_duration_ms_total counter')
  lines.push(`db_query_duration_ms_total ${Math.round(store.db.totalDurationMs)}`)

  if (store.db.totalQueries > 0) {
    const dbAvg = Math.round(store.db.totalDurationMs / store.db.totalQueries)
    lines.push('# HELP db_query_duration_avg_ms Average database query duration in ms.')
    lines.push('# TYPE db_query_duration_avg_ms gauge')
    lines.push(`db_query_duration_avg_ms ${dbAvg}`)
  }

  lines.push('# HELP db_slow_queries_total Slow database queries (>100ms).')
  lines.push('# TYPE db_slow_queries_total counter')
  lines.push(`db_slow_queries_total ${store.db.slowQueries}`)

  // --- AI 指标 ---
  lines.push('# HELP ai_calls_total Total AI model calls.')
  lines.push('# TYPE ai_calls_total counter')
  lines.push(`ai_calls_total ${store.ai.totalCalls}`)

  lines.push('# HELP ai_tokens_total Total tokens consumed.')
  lines.push('# TYPE ai_tokens_total counter')
  lines.push(`ai_tokens_total ${store.ai.totalTokens}`)

  if (store.ai.totalCalls > 0) {
    const aiAvg = Math.round(store.ai.totalDurationMs / store.ai.totalCalls)
    lines.push('# HELP ai_call_duration_avg_ms Average AI call duration in ms.')
    lines.push('# TYPE ai_call_duration_avg_ms gauge')
    lines.push(`ai_call_duration_avg_ms ${aiAvg}`)
  }

  const aiSorted = [...store.ai.ttftBuckets.samples].sort((a, b) => a - b)
  lines.push('# HELP ai_ttft_ms Time-to-first-token in ms.')
  lines.push('# TYPE ai_ttft_ms summary')
  lines.push(`ai_ttft_ms{quantile="0.50"} ${calcPercentile(aiSorted, 50)}`)
  lines.push(`ai_ttft_ms{quantile="0.95"} ${calcPercentile(aiSorted, 95)}`)
  lines.push(`ai_ttft_ms{quantile="0.99"} ${calcPercentile(aiSorted, 99)}`)

  // --- 运行时 ---
  lines.push('# HELP process_uptime_seconds Application uptime in seconds.')
  lines.push('# TYPE process_uptime_seconds gauge')
  lines.push(`process_uptime_seconds ${uptime}`)

  return lines.join('\n') + '\n'
}

/** 重置 Metrics（用于测试） */
export function resetMetrics() {
  store.startTime = Date.now()
  store.requests = { total: 0, byEndpoint: {} }
  store.db = { totalQueries: 0, totalDurationMs: 0, slowQueries: 0 }
  store.ai = { totalCalls: 0, totalDurationMs: 0, totalTokens: 0, ttftBuckets: createLatencyBucket() }
  store.memory = { compaction: {}, durations: {}, fact: {}, fallback: {}, resolve: {} }
}
