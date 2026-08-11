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
    logger.debug({ traceId, method, path }, 'request started')

    if (event.node?.res) {
      event.node.res.once('finish', () => {
        const duration = Date.now() - start
        const statusCode = event.node.res.statusCode || 200
        recordRequest(method, path, statusCode, duration)
        logger.info({ traceId, method, path, statusCode, duration }, 'request completed')
      })
    }
  })
}
