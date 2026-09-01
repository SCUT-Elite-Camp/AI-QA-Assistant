import { useSession, type HTTPEvent, type Session } from 'nitro/h3'

export interface UserSession extends Session {
  user?: {
    id: string
    name: string
    avatar: string
    username: string
  }
}

export function getSessionSecret (environment: Record<string, string | undefined> = process.env): string {
  const configuredSecret = environment.SESSION_SECRET?.trim()
  if (configuredSecret) return configuredSecret

  if (environment.NODE_ENV === 'development') {
    return 'development_only_session_secret_key_qa_assistant_2026'
  }

  throw new Error('SESSION_SECRET must be configured outside development')
}

export function useUserSession (event: HTTPEvent) {
  return useSession<UserSession>(event, {
    name: 'qa_session',
    password: getSessionSecret(),
    cookie: {
      sameSite: 'lax',
      secure: false,
      httpOnly: false,
      path: '/'
    }
  })
}


