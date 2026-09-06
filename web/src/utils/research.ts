import type { ResearchJob } from '../types/research'

export function isResearchTerminal(job: ResearchJob): boolean {
  return ['completed', 'failed', 'cancelled'].includes(job.status)
}
export function formatResearchError(error: unknown): string {
  if (typeof error === 'object' && error !== null) {
    const candidate = error as { data?: { detail?: string | { message?: string } }, message?: string }
    const detail = candidate.data?.detail
    if (typeof detail === 'string') return detail
    if (detail?.message) return detail.message
    if (candidate.message) return candidate.message
  }
  return 'Research 服务暂时不可用，请稍后重试。'
}

