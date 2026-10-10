import type { ResearchJob } from '../types/research'

export function researchSourceHref(researchId: string, docId: string): string {
  return `/api/research/jobs/${encodeURIComponent(researchId)}/documents/${encodeURIComponent(docId)}/source`
}

export function isResearchTerminal(job: ResearchJob): boolean {
  return ['completed', 'failed', 'cancelled'].includes(job.status)
}
export function formatResearchError(error: unknown): string {
  if (typeof error === 'object' && error !== null) {
    const candidate = error as { data?: { detail?: string | { message?: string, code?: string } }, message?: string }
    const detail = candidate.data?.detail
    if (typeof detail === 'string') return detail
    if (detail?.code) {
      const messages: Record<string, string> = {
        research_identity_required: '请登录后使用 Research。',
        research_actor_forbidden: '当前账号无法访问 Research，请检查账号状态。',
        research_source_forbidden: '所选资料不在当前账号的授权范围内。',
        research_source_access_revoked: '资料权限已变更，当前报告不可访问，请重新选择资料。',
        research_permission_unavailable: '暂时无法确认资料权限，请稍后重试。',
        research_source_version_changed: '资料已更新，请重新发起研究以确认最新版本。',
      }
      if (messages[detail.code]) return messages[detail.code]!
    }
    if (detail?.message) return detail.message
    if (candidate.message) return candidate.message
  }
  return 'Research 服务暂时不可用，请稍后重试。'
}
