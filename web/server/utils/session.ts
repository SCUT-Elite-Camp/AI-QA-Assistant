import { useSession, type HTTPEvent, type Session } from 'nitro/h3'

export interface UserSession extends Session {
  user?: {
    id: string
    name: string
    avatar: string
    username: string
  }
}

export function useUserSession (event: HTTPEvent) {
  const secret = process.env.SESSION_SECRET || 'default_fallback_session_secret_key_qa_assistant_2026'
  return useSession<UserSession>(event, {
    name: 'qa_session',
    password: secret,
    cookie: {
      sameSite: 'lax',
      secure: false,
      httpOnly: false,
      path: '/'
    }
  })
}


