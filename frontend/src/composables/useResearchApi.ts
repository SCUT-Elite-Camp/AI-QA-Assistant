import { $fetch } from 'ofetch'
import type { ResearchApprovalRequest, ResearchEventsResponse, ResearchInteractionResponse, ResearchJob, ResearchPlan, ResearchPlanRevisionRequest, ResearchProgress, ResearchReport, ResearchRequest } from '../types/research'
import { mockApproveResearch, mockCancelResearch, mockCreateResearch, mockGetEvents, mockGetPlan, mockGetProgress, mockGetReport, mockGetResearch, mockReviseResearchPlan } from '../mocks/research'
import { useCsrf } from './useCsrf'

const useMock = import.meta.env.VITE_RESEARCH_USE_MOCK === 'true'
const apiBase = '/api/research'

export function useResearchApi() {
  const { csrf, headerName } = useCsrf()
  const mutationHeaders = () => ({ [headerName]: csrf() })
  async function createJob(request: ResearchRequest): Promise<ResearchJob> {
    if (useMock) return mockCreateResearch(request)
    return $fetch<ResearchJob>(`${apiBase}/jobs`, { method: 'POST', headers: mutationHeaders(), body: request })
  }

  async function getJob(researchId: string): Promise<ResearchJob> {
    if (useMock) return mockGetResearch(researchId)
    return $fetch<ResearchJob>(`${apiBase}/jobs/${encodeURIComponent(researchId)}`)
  }

  async function getPlan(researchId: string): Promise<ResearchPlan> {
    if (useMock) return mockGetPlan(researchId)
    return $fetch<ResearchPlan>(`${apiBase}/jobs/${encodeURIComponent(researchId)}/plan`)
  }

  async function approveJob(researchId: string, approval: ResearchApprovalRequest): Promise<ResearchJob> {
    if (useMock) return mockApproveResearch(researchId)
    return $fetch<ResearchJob>(`${apiBase}/jobs/${encodeURIComponent(researchId)}/approve`, { method: 'POST', headers: mutationHeaders(), body: approval })
  }

  async function revisePlan(researchId: string, revision: ResearchPlanRevisionRequest): Promise<ResearchPlan> {
    if (useMock) return mockReviseResearchPlan(researchId, revision)
    return $fetch<ResearchPlan>(`${apiBase}/jobs/${encodeURIComponent(researchId)}/plan/revisions`, {
      method: 'POST',
      headers: mutationHeaders(),
      body: revision,
    })
  }

  async function cancelJob(researchId: string): Promise<ResearchJob> {
    if (useMock) return mockCancelResearch(researchId)
    return $fetch<ResearchJob>(`${apiBase}/jobs/${encodeURIComponent(researchId)}/cancel`, { method: 'POST', headers: mutationHeaders() })
  }

  async function sendMessage(researchId: string, message: string): Promise<ResearchInteractionResponse> {
    return $fetch<ResearchInteractionResponse>(`${apiBase}/jobs/${encodeURIComponent(researchId)}/messages`, {
      method: 'POST',
      headers: mutationHeaders(),
      body: { message },
    })
  }

  async function getReport(researchId: string): Promise<ResearchReport> {
    if (useMock) return mockGetReport(researchId)
    return $fetch<ResearchReport>(`${apiBase}/jobs/${encodeURIComponent(researchId)}/report`)
  }

  async function getProgress(researchId: string): Promise<ResearchProgress> {
    if (useMock) return mockGetProgress(researchId)
    return $fetch<ResearchProgress>(`${apiBase}/jobs/${encodeURIComponent(researchId)}/progress`)
  }

  async function getEvents(researchId: string, afterEventId = 0, limit = 50): Promise<ResearchEventsResponse> {
    if (useMock) return mockGetEvents(researchId, afterEventId, limit)
    return $fetch<ResearchEventsResponse>(`${apiBase}/jobs/${encodeURIComponent(researchId)}/events`, {
      query: { after_event_id: afterEventId, limit },
    })
  }

  return { createJob, getJob, getPlan, revisePlan, approveJob, cancelJob, sendMessage, getReport, getProgress, getEvents, useMock, apiBase }
}
