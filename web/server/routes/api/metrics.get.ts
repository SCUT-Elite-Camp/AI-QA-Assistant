import { defineHandler } from 'nitro'
import { getMetrics } from '../../utils/metrics'

/**
 * GET /api/metrics
 * 暴露服务端可观测指标，JSON 格式。
 * 可供 Prometheus 或其他监控系统抓取。
 */
export default defineHandler(() => {
  return getMetrics()
})
