/** Shared configuration for server-to-server calls to the Agent service. */
export function resolveAgentBaseUrl (environment: Record<string, string | undefined>): string {
  const configuredUrl = environment.AGENT_BASE_URL?.trim()
  if (configuredUrl) return configuredUrl.replace(/\/+$/, '')

  if (environment.NODE_ENV === 'development') {
    return 'http://127.0.0.1:8000'
  }

  throw new Error('AGENT_BASE_URL must be configured outside development')
}

export function getAgentBaseUrl (environment: Record<string, string | undefined> = process.env): string {
  return resolveAgentBaseUrl(environment)
}

export function getAgentInternalToken (environment: Record<string, string | undefined> = process.env): string | undefined {
  return environment.AGENT_INTERNAL_TOKEN?.trim() || undefined
}
