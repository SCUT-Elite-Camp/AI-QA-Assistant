function createFallbackLogger(name: string) {
  return {
    trace: (...args: any[]) => console.trace(`[${name}]`, ...args),
    debug: (...args: any[]) => console.debug(`[${name}]`, ...args),
    info: (...args: any[]) => console.info(`[${name}]`, ...args),
    warn: (...args: any[]) => console.warn(`[${name}]`, ...args),
    error: (...args: any[]) => console.error(`[${name}]`, ...args),
    fatal: (...args: any[]) => console.error(`[${name}] [FATAL]`, ...args),
  }
}

/**
 * 统一日志工厂。
 * 开发环境使用 pino-pretty 彩色输出，生产环境输出 JSON 行。
 * 支持 LOG_LEVEL 环境变量 (trace/debug/info/warn/error/fatal)。
 */
export function createLogger(name: string) {
  try {
    const pino = require('pino')
    const level = process.env.LOG_LEVEL || (process.env.NODE_ENV === 'production' ? 'info' : 'debug')

    const transport = process.env.NODE_ENV === 'production'
      ? undefined
      : {
          target: 'pino-pretty',
          options: {
            colorize: true,
            translateTime: 'SYS:HH:MM:ss.l',
            ignore: 'pid,hostname',
            messageFormat: '[{traceId}] {name} - {msg}',
          },
        }

    return pino({
      name,
      level,
      serializers: {
        err: pino.stdSerializers?.err,
        error: pino.stdSerializers?.err,
      },
      mixin() {
        return {}
      },
      transport: transport as any,
    })
  } catch {
    return createFallbackLogger(name)
  }
}

/**
 * 默认 logger 实例
 */
export const logger = createLogger('web')

type MemoryLogEvent =
  | { event: 'memory_resolve', source: 'disabled' | 'trusted_context' | 'legacy', outcome: 'success' | 'fallback' | 'rejected' }
  | { event: 'memory_compaction', outcome: 'skipped' | 'planned' | 'conflict' | 'failed' }
  | { event: 'memory_fact', action: 'proposed' | 'suppressed' | 'recalled', outcome: 'success' | 'disabled' | 'sensitive' | 'empty' | 'failed' }
  | { event: 'memory_fallback', reason: 'agent_disabled' | 'internal_error' | 'context_error' }

const MEMORY_LOG_EVENTS = new Set(['memory_resolve', 'memory_compaction', 'memory_fact', 'memory_fallback'])

/**
 * Strip unknown keys before Memory observability reaches the logger. This
 * deliberately rejects query, Fact, Snapshot, Tail, ID and Error payloads.
 */
export function createSafeMemoryLogPayload (input: Record<string, unknown>): Record<string, string> | undefined {
  if (!MEMORY_LOG_EVENTS.has(String(input.event))) return undefined
  switch (input.event) {
    case 'memory_resolve':
      if (typeof input.source !== 'string' || typeof input.outcome !== 'string') return undefined
      return { event: input.event, source: input.source, outcome: input.outcome }
    case 'memory_compaction':
      if (typeof input.outcome !== 'string') return undefined
      return { event: input.event, outcome: input.outcome }
    case 'memory_fact':
      if (typeof input.action !== 'string' || typeof input.outcome !== 'string') return undefined
      return { event: input.event, action: input.action, outcome: input.outcome }
    case 'memory_fallback':
      if (typeof input.reason !== 'string') return undefined
      return { event: input.event, reason: input.reason }
    default:
      return undefined
  }
}

export function logMemoryEvent (event: MemoryLogEvent) {
  const payload = createSafeMemoryLogPayload(event)
  if (payload) logger.info(payload, 'memory event')
}

