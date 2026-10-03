import { defineHandler } from 'nitro'
import { z } from 'zod'
import { readBody } from 'nitro/h3'
import { logger } from '../../utils/logger'

/**
 * POST /api/telemetry
 * 接收前端 Web Vitals 上报（LCP, FCP, INP）。
 * 仅记录日志，不持久化（可按需扩展）。
 */
export default defineHandler(async (event) => {
  const traceId = (event as any).__traceId || 'unknown'

  const body = await readBody(event)
  const schema = z.object({
    name: z.enum(['LCP', 'FCP', 'INP']),
    value: z.number(),
    rating: z.string(),
    page: z.string().optional(),
    timestamp: z.number().optional(),
  })
  const { name, value, rating, page } = schema.parse(body)

  logger.info({ traceId, webVital: name, value, rating, page }, 'web vital reported')

  return { success: true }
})
