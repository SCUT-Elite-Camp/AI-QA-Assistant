import { getRequestIP, type HTTPEvent } from 'nitro/h3'

export function developmentLoginAllowed(environment: Record<string, string | undefined>, hostname: string, address?: string): boolean {
  const enabled = environment.NODE_ENV === 'development' || environment.ALLOW_DEV_LOGIN === 'true'
  const localHost = ['localhost', '127.0.0.1', '[::1]', '::1'].includes(hostname)
  const localAddress = address === '::1' || address === '::ffff:127.0.0.1' || address === '127.0.0.1'
  return enabled && localHost && localAddress
}

export function isLocalDevelopmentRequest(event: HTTPEvent): boolean {
  return developmentLoginAllowed(process.env, new URL(event.req.url).hostname,
    getRequestIP(event, { xForwardedFor: false }))
}
