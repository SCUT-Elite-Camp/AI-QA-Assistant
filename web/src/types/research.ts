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
export type ResearchStageStatus = 'pending' | 'running' | 'completed' | 'failed'
export type ResearchEventType =
  | 'job_created'
  | 'plan_approved'
  | 'stage_started'
  | 'stage_completed'
  | 'task_started'
  | 'task_completed'
  | 'task_failed'
  | 'task_blocked'
  | 'report_ready'
  | 'job_completed'
  | 'job_failed'
  | 'job_cancelled'

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

export interface ResearchStageProgress {
  key: string
  label: string
  status: ResearchStageStatus
  started_at: string | null
  completed_at: string | null
}

export interface ResearchTaskProgress {
  task_id: string
  question: string
  status: ResearchTaskStatus
  evidence_count: number
}

export interface ResearchProgressError {
  stage: string
  code: string
  message: string
}

export interface ResearchProgress {
  schema_version: 'research.progress.v1'
  research_id: string
  status: ResearchJobStatus
  result_status: ResearchResultStatus | null
  current_stage: string
  progress_percent: number
  task_total: number
  task_completed: number
  evidence_count: number
  claim_count: number
  started_at: string
  updated_at: string
  stages: ResearchStageProgress[]
  tasks: ResearchTaskProgress[]
  error: ResearchProgressError | null
}

export interface ResearchEvent {
  event_id: number
  research_id: string
  event_key: string
  event_type: ResearchEventType
  stage: string | null
  task_id: string | null
  message: string
  payload: Record<string, string | number | boolean | null>
  created_at: string
}

export interface ResearchEventsResponse {
  schema_version: 'research.events.v1'
  research_id: string
  events: ResearchEvent[]
  next_after_event_id: number
}

export interface ResearchApiError {
  statusCode?: number
  code: string
  message: string
}
