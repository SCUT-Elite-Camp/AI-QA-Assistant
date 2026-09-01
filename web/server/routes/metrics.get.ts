import { defineHandler } from 'nitro'
import { setHeader } from 'h3'
import { getPrometheusMetrics } from '../utils/metrics'

/**
 * GET /metrics
 * Prometheus 文本格式指标端点，供 Prometheus Server 定期抓取。
 *
 * 暴露指标：
 * - http_requests_total: HTTP 请求总数（按 method/path/status_code）
 * - http_request_duration_ms: 请求延迟直方图 (sum/count/avg/p50/p95/p99)
 * - http_request_duration_overall_ms: 全局延迟分位数 (p50/p95/p99)
 * - http_errors_total: 错误响应总数 (4xx+5xx)
 * - http_throughput_requests_per_second: 近似吞吐量
 * - db_queries_total / db_query_duration_* / db_slow_queries_total: 数据库指标
 * - ai_calls_total / ai_tokens_total / ai_call_duration_avg_ms / ai_ttft_ms: AI 指标
 * - process_uptime_seconds: 应用运行时间
 */
export default defineHandler((event) => {
  setHeader(event, 'Content-Type', 'text/plain; version=0.0.4; charset=utf-8')
  return getPrometheusMetrics()
})
