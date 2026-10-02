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
  }
}

/** 重置 Metrics（用于测试） */
export function resetMetrics() {
  store.startTime = Date.now()
  store.requests = { total: 0, byEndpoint: {} }
  store.db = { totalQueries: 0, totalDurationMs: 0, slowQueries: 0 }
  store.ai = { totalCalls: 0, totalDurationMs: 0, totalTokens: 0, ttftBuckets: createLatencyBucket() }
}
