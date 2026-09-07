export type ResearchJobStatus =
  | 'created'
  | 'planning'
  | 'awaiting_approval'
  | 'ready'
  | 'researching'
  | 'synthesizing'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type ResearchResultStatus = 'complete' | 'degraded'
export type ResearchTaskStatus = 'pending' | 'ready' | 'running' | 'succeeded' | 'failed' | 'blocked'

export interface SourceScope {
  knowledge_base_ids: string[]
  document_ids: string[]
  topic: string
}

export interface ReportSpec {
  format: 'markdown'
  language: 'zh-CN' | 'en-US'
  title: string
  sections: string[]
  include_citations: boolean
  include_limitations: boolean
}

export interface ResearchRequest {
  schema_version: 'research.v2'
  query: string
  source_scope: SourceScope
  report_spec: ReportSpec
  profile: 'standard'
  user_notes?: string | null
}

export interface AcceptanceCriterion {
  criterion_id: string
  description: string
  requires_evidence: boolean
  dimension: string
  target: string
  required: boolean
}

export interface ResearchTask {
  task_id: string
  question: string
  purpose: string
  dependencies: string[]
  allowed_tools: string[]
  source_ids: string[]
  acceptance_criteria: AcceptanceCriterion[]
  priority: 'critical' | 'normal' | 'optional'
  max_actions: number
  status: ResearchTaskStatus
}

export interface ResearchBudget {
  max_tasks: number
  max_actions: number
  max_tool_calls: number
  max_tokens: number
  max_runtime_seconds: number
}

export interface ResearchPlan {
  schema_version: 'research.v1' | 'research.v2'
  research_id: string
  version: number
  objective: string
  out_of_scope: string[]
  source_scope: SourceScope
  report_spec: ReportSpec
  manifest_hash: string | null
  tasks: ResearchTask[]
  budget: ResearchBudget
  status: 'draft' | 'awaiting_approval' | 'approved' | 'superseded'
}

export interface ResearchJob {
  schema_version: 'research.v2'
  research_id: string
  user_id: string
  request: ResearchRequest
  status: ResearchJobStatus
  result_status: ResearchResultStatus | null
  plan_version: number | null
  manifest_hash: string | null
  current_stage: string
  current_task_id: string | null
  task_total: number
  task_completed: number
  evidence_count: number
  failure_stage: string | null
  error_code: string | null
  created_at: string
  updated_at: string
  claim_count?: number
}

export interface ResearchReport {
  report_id: string
  research_id: string
  markdown: string
  result_status: ResearchResultStatus
  claim_ids: string[]
  evidence_ids: string[]
  generated_at: string
}

export interface ResearchApprovalRequest {
  plan_version: number
  manifest_hash: string
}

export interface ResearchStageDefinition {
  key: string
  label: string
  description: string
  progress: number
}

export type ResearchStageViewStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface ResearchStageView extends ResearchStageDefinition {
  status: ResearchStageViewStatus
}

export interface ResearchApiError {
  statusCode?: number
  code: string
  message: string
}

