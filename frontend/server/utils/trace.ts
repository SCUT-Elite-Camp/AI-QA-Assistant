import { randomUUID } from 'node:crypto'
import { getHeader, setHeader } from 'nitro/h3'
import type { H3Event } from 'nitro'

const TRACE_HEADER = 'x-trace-id'

/**
 * 从请求中获取或生成 trace_id。
 * 优先使用客户端传入的 x-trace-id，否则自动生成 UUID。
 * 同时将 trace_id 设置到响应头中。
 */
export function getOrCreateTraceId(event: H3Event): string {
  const existing = getHeader(event, TRACE_HEADER)
  if (existing) {
    setHeader(event, TRACE_HEADER, existing)
    return existing
  }

  const traceId = randomUUID()
  setHeader(event, TRACE_HEADER, traceId)
  return traceId
}

/**
 * 从事件上下文中获取 trace_id（需要先调用 getOrCreateTraceId）
 */
export function getTraceId(event: H3Event): string | undefined {
  return getHeader(event, TRACE_HEADER) || undefined
}
