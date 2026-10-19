import type { ResearchEvent, ResearchJob } from '../types/research'

export function researchEventLabel(event: ResearchEvent): string {
  const messages: Record<ResearchEvent['event_type'], string> = {
    job_created: 'Research created', plan_revised: 'Plan revised. Approval is required.',
    plan_approved: 'Research plan approved', job_recovered: 'Restored from checkpoint',
    stage_started: 'Research stage started', stage_completed: 'Research stage completed',
    task_started: 'Research task started', task_completed: 'Research task completed',
    task_failed: 'Research task did not obtain verifiable evidence',
    task_blocked: 'Research task skipped because a dependency did not complete',
    report_ready: 'Research report ready', job_completed: 'Research complete',
    report_reviewed: 'Report review completed', report_revised: 'Report revised; independent review required',
    job_failed: 'Research failed', job_cancelled: 'Research cancelled',
    user_message: 'User message', assistant_message: 'Assistant response',
    conflict_resolved: 'Conflict resolution saved',
  }
  // Keep historical stored content intact while displaying English lifecycle UI.
  if (['stage_started', 'stage_completed'].includes(event.event_type)
    && !/[\u3400-\u9fff]/.test(event.message)) return event.message
  return messages[event.event_type]
}

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
        research_identity_required: 'Sign in to use Deep Research.',
        research_actor_forbidden: 'This account cannot access Deep Research. Check your account status.',
        research_source_forbidden: 'No accessible sources are available, or the requested sources are outside your permissions.',
        research_source_access_revoked: 'Source permissions have changed. Start a new research job with your current access.',
        research_permission_unavailable: 'Source permissions cannot be verified right now. Please try again.',
        research_source_version_changed: 'Sources have changed. Start a new research job using the latest versions.',
        document_version_changed: 'Sources have changed. Start a new research job using the latest versions.',
      }
      if (messages[detail.code]) return messages[detail.code]!
    }
    if (detail?.message) return detail.message
    if (candidate.message) return candidate.message
  }
  return 'Deep Research is temporarily unavailable. Please try again.'
}
