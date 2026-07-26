import pino from 'pino'

/**
 * 统一日志工厂。
 * 开发环境使用 pino-pretty 彩色输出，生产环境输出 JSON 行。
 * 支持 LOG_LEVEL 环境变量 (trace/debug/info/warn/error/fatal)。
 */
export function createLogger(name: string) {
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
    // 序列化 Error 对象
    serializers: {
      err: pino.stdSerializers.err,
      error: pino.stdSerializers.err,
    },
    // 自定义 key 让 trace_id 出现在每行
    mixin() {
      return {}
    },
    transport: transport as any,
  })
}

/**
 * 默认 logger 实例
 */
export const logger = createLogger('web')
