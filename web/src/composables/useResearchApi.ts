import { $fetch } from 'ofetch'
import type { ResearchApprovalRequest, ResearchJob, ResearchPlan, ResearchReport, ResearchRequest } from '../types/research'
import { mockApproveResearch, mockCancelResearch, mockCreateResearch, mockGetPlan, mockGetReport, mockGetResearch } from '../mocks/research'

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

  return { createJob, getJob, getPlan, approveJob, cancelJob, getReport, useMock, apiBase }
}

