import { $fetch } from 'ofetch'
import type { ResearchApprovalRequest, ResearchEventsResponse, ResearchJob, ResearchPlan, ResearchProgress, ResearchReport, ResearchRequest } from '../types/research'
import { mockApproveResearch, mockCancelResearch, mockCreateResearch, mockGetEvents, mockGetPlan, mockGetProgress, mockGetReport, mockGetResearch } from '../mocks/research'

const useMock = import.meta.env.VITE_RESEARCH_USE_MOCK === 'true'
const configuredBase = (import.meta.env.VITE_RESEARCH_API_BASE || 'http://127.0.0.1:8000').replace(/\/$/, '')
const apiBase = `${configuredBase}/api/research`

export function useResearchApi() {
  async function createJob(request: ResearchRequest): Promise<ResearchJob> {
    if (useMock) return mockCreateResearch(request)
    return $fetch<ResearchJob>(`${apiBase}/jobs`, { method: 'POST', headers: { 'X-User-ID': 'web-user' }, body: request })
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
    return $fetch<ResearchJob>(`${apiBase}/jobs/${encodeURIComponent(researchId)}/approve`, { method: 'POST', headers: { 'X-User-ID': 'web-user' }, body: approval })
  }

  async function cancelJob(researchId: string): Promise<ResearchJob> {
    if (useMock) return mockCancelResearch(researchId)
    return $fetch<ResearchJob>(`${apiBase}/jobs/${encodeURIComponent(researchId)}/cancel`, { method: 'POST' })
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

  return { createJob, getJob, getPlan, approveJob, cancelJob, getReport, getProgress, getEvents, useMock, apiBase }
}

