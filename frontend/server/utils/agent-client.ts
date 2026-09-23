/**
 * Agent 层服务客户端。
 *
 * Agent 层（FastAPI，port 8000）通过共享密钥（Bearer token）校验调用方身份，
 * 以阻止外部直连 agent 端口伪造 user_id 绕过 Web 层权限隔离。
 *
 * 本模块为 Web -> Agent 的所有 HTTP 调用提供统一入口，自动附加
 * `Authorization: Bearer <AGENT_API_KEY>` 请求头。AGENT_API_KEY 从 Web 服务
 * 环境变量读取（与 Agent 层配置的值必须一致）。
 */

const AGENT_BASE_URL = process.env.AGENT_BASE_URL || 'http://127.0.0.1:8000'

function agentHeaders(extra?: Record<string, string>): Record<string, string> {
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${process.env.AGENT_API_KEY || ''}`,
    ...extra,
  }
}

/**
 * 调用 Agent 业务接口（自动附带认证头）。
 * 与原生 fetch 签名一致，便于替换现有调用点。
 */
export function agentFetch(path: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(agentHeaders())
  if (init?.headers) {
    const extra = new Headers(init.headers)
    extra.forEach((value, key) => headers.set(key, value))
  }
  return fetch(`${AGENT_BASE_URL}${path}`, { ...init, headers })
}

export { AGENT_BASE_URL, agentHeaders }
