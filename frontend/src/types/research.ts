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
  | 'plan_revised'
  | 'plan_approved'
  | 'job_recovered'
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
  | 'user_message'
  | 'assistant_message'
  | 'conflict_resolved'

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

export interface ResearchPlanRevisionRequest {
  base_version: number
  objective: string
  tasks: ResearchTask[]
  report_spec: ReportSpec
  revision_note: string
}

export interface ResearchInteractionResponse {
  action: string
  message: string
  job: ResearchJob
  plan: ResearchPlan | null
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
  citations: ResearchCitation[]
  conflicts: ResearchConflict[]
  limitations: ResearchLimitation[]
  generated_at: string
}

export interface ResearchCitation {
  number: number
  evidence_id: string
  evidence_ids: string[]
  doc_id: string
  title: string
  source_url?: string | null
  source_type: string
  authority: string
  authority_rank: number
  document_version: string | null
  effective_at: string | null
  updated_at: string | null
  locator: string
  excerpt: string
  content_hash: string
}

export interface ResearchConflictAlternative {
  citation_number: number
  evidence_id: string
  source_title: string
  value_summary: string
  document_version: string | null
  effective_at: string | null
  updated_at: string | null
  authority: string
  authority_rank: number
}

export interface ResearchConflict {
  conflict_id: string
  subject: string
  conflict_type: 'numeric' | 'version' | 'source'
  summary: string
  alternatives: ResearchConflictAlternative[]
  resolution_status: 'unresolved' | 'resolved_by_authority' | 'resolved_by_user'
  resolution: string
}

export interface ResearchLimitation {
  code: string
  message: string
  evidence_ids: string[]
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
  metrics: ResearchRunMetrics
  error: ResearchProgressError | null
}

export interface ResearchRunMetrics {
  elapsed_ms: number
  actions_used: number
  tool_calls: number
  documents_read: number
  evidence_accepted: number
  evidence_rejected: number
  retry_count: number
  recovery_count: number
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
