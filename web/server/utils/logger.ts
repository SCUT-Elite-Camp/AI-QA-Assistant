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

