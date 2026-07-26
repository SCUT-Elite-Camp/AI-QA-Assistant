import { getMethod, getRequestPath } from 'nitro/h3'
import { getOrCreateTraceId } from '../utils/trace'
import { logger } from '../utils/logger'
import { recordRequest } from '../utils/metrics'

/**
 * Observability Nitro Plugin
 * - 为每个请求注入 trace_id
 * - 响应完成后记录请求耗时和 metrics
 */
export default (nitroApp: any) => {
  nitroApp.hooks.hook('request', (event: any) => {
    const traceId = getOrCreateTraceId(event)
    const start = Date.now()
    const method = getMethod(event)
    const path = getRequestPath(event)

    event.__traceId = traceId
    event.__observabilityStart = start
    event.__observabilityMethod = method
    event.__observabilityPath = path

    logger.debug({ traceId, method, path }, 'request started')
  })

  nitroApp.hooks.hook('afterResponse', (event: any) => {
    const start = event.__observabilityStart
    const traceId = event.__traceId || 'unknown'
    const method = event.__observabilityMethod || 'GET'
    const path = event.__observabilityPath || '/'

    if (start) {
      const duration = Date.now() - start
      const statusCode = event.node.res.statusCode || 200
      recordRequest(method, path, statusCode, duration)
      logger.info({ traceId, method, path, statusCode, duration }, 'request completed')
    }
  })
}
