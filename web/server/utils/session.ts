import { useSession, type HTTPEvent, type Session } from 'nitro/h3'

export interface UserSession extends Session {
  user?: {
    id: string
    name: string
    avatar: string
    username: string
    role?: 'admin' | 'user'
    disabled?: boolean
    /** 用户所属部门 ID 列表（SSO/LDAP 同步时写入，可参与 Agent 层部门级授权） */
    departmentIds?: string[]
  }
}

export function useUserSession (event: HTTPEvent) {
  if (!process.env.SESSION_SECRET) {
    throw new Error('SESSION_SECRET environment variable is not set')
  }
  return useSession<UserSession>(event, {
    password: process.env.SESSION_SECRET
  })
}
