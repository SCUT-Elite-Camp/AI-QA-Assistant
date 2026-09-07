import type { ResearchJob, ResearchPlan, ResearchReport, ResearchRequest } from '../types/research'

interface MockRecord {
  job: ResearchJob
  plan: ResearchPlan
  approvedAt: number | null
}

const records = new Map<string, MockRecord>()
const manifestHash = '8a5599e8d44944d6e4d1d563aea17ab79b8a4d18e75287adf3ad1f90b073e0a1'

function now() {
  return new Date().toISOString()
}

function makePlan(researchId: string, request: ResearchRequest): ResearchPlan {
  const sourceIds = [...request.source_scope.document_ids, ...request.source_scope.knowledge_base_ids]
  const criterion = (id: string, target: string) => ({
    criterion_id: id,
    description: `general: ${target}`,
    requires_evidence: true,
    dimension: 'general',
    target,
    required: true,
  })
  return {
    schema_version: 'research.v2', research_id: researchId, version: 1,
    objective: request.query, out_of_scope: ['冻结资料范围以外的信息'], source_scope: request.source_scope,
    report_spec: request.report_spec, manifest_hash: manifestHash, status: 'awaiting_approval',
    budget: { max_tasks: 8, max_actions: 32, max_tool_calls: 32, max_tokens: 20000, max_runtime_seconds: 300 },
    tasks: [
      { task_id: 'task-1', question: `定位核心事实：${request.query}`, purpose: '定位与研究目标直接相关的原始事实', dependencies: [], allowed_tools: ['keyword_search', 'read_document_range'], source_ids: sourceIds, acceptance_criteria: [criterion('task-1-C1', '核心事实有原文依据')], priority: 'critical', max_actions: 4, status: 'pending' },
      { task_id: 'task-2', question: '读取并核验候选事实对应的原始文档位置', purpose: '将搜索观察提升为可追溯证据', dependencies: ['task-1'], allowed_tools: ['keyword_search', 'read_document_range'], source_ids: sourceIds, acceptance_criteria: [criterion('task-2-C1', '证据包含稳定原文位置')], priority: 'normal', max_actions: 4, status: 'pending' },
      { task_id: 'task-3', question: '整理研究结论并标记资料限制', purpose: '形成可信且披露限制的报告', dependencies: ['task-2'], allowed_tools: ['keyword_search', 'read_document_range'], source_ids: sourceIds, acceptance_criteria: [criterion('task-3-C1', '结论与限制均被明确说明')], priority: 'normal', max_actions: 4, status: 'pending' },
    ],
  }
}

export function mockCreateResearch(request: ResearchRequest): ResearchJob {
  const researchId = `research-web-${crypto.randomUUID()}`
  const createdAt = now()
  const job: ResearchJob = {
    schema_version: 'research.v2', research_id: researchId, user_id: 'web-user', request,
    status: 'created', result_status: null, plan_version: null, manifest_hash: null,
    current_stage: 'created', current_task_id: null, task_total: 0, task_completed: 0,
    evidence_count: 0, failure_stage: null, error_code: null, created_at: createdAt, updated_at: createdAt,
  }
  records.set(researchId, { job, plan: makePlan(researchId, request), approvedAt: null })
  return structuredClone(job)
}

function advance(record: MockRecord) {
  const elapsed = Date.now() - new Date(record.job.created_at).getTime()
  if (!record.approvedAt) {
    if (elapsed > 1400) Object.assign(record.job, { status: 'awaiting_approval', current_stage: 'awaiting_approval', plan_version: 1, manifest_hash: manifestHash, task_total: 3, updated_at: now() })
    else if (elapsed > 350) Object.assign(record.job, { status: 'planning', current_stage: 'planning', updated_at: now() })
    return
  }
  const runElapsed = Date.now() - record.approvedAt
  const states = [
    [0, 'ready', 'ready', 0, 0], [900, 'researching', 'execute_tasks', 0, 0],
    [1800, 'researching', 'execute_tasks', 1, 2], [2700, 'researching', 'execute_tasks', 2, 4],
    [3600, 'researching', 'coverage', 3, 6], [4400, 'researching', 'generate_claims', 3, 6],
    [5200, 'researching', 'structural_verification', 3, 6], [6000, 'researching', 'semantic_verification', 3, 6],
    [6800, 'synthesizing', 'render_report', 3, 6], [7600, 'synthesizing', 'finalize', 3, 6],
    [8400, 'completed', 'completed', 3, 6],
  ] as const
  const state = [...states].reverse().find(item => runElapsed >= item[0]) ?? states[0]
  Object.assign(record.job, { status: state[1], current_stage: state[2], task_completed: state[3], evidence_count: state[4], current_task_id: state[1] === 'researching' && state[3] < 3 ? `task-${state[3] + 1}` : null, updated_at: now() })
  if (state[1] === 'completed') record.job.result_status = 'complete'
}

export function mockGetResearch(researchId: string): ResearchJob {
  const record = records.get(researchId)
  if (!record) throw new Error('Research Job 不存在或 Mock 页面已刷新。')
  advance(record)
  return structuredClone(record.job)
}

export function mockGetPlan(researchId: string): ResearchPlan {
  const record = records.get(researchId)
  if (!record) throw new Error('Research Plan 不存在。')
  return structuredClone(record.plan)
}

export function mockApproveResearch(researchId: string): ResearchJob {
  const record = records.get(researchId)
  if (!record) throw new Error('Research Job 不存在。')
  record.approvedAt = Date.now()
  record.plan.status = 'approved'
  Object.assign(record.job, { status: 'ready', current_stage: 'ready', updated_at: now() })
  return structuredClone(record.job)
}

export function mockCancelResearch(researchId: string): ResearchJob {
  const record = records.get(researchId)
  if (!record) throw new Error('Research Job 不存在。')
  Object.assign(record.job, { status: 'cancelled', updated_at: now() })
  record.approvedAt = null
  return structuredClone(record.job)
}

export function mockGetReport(researchId: string): ResearchReport {
  const record = records.get(researchId)
  if (!record || record.job.status !== 'completed') throw new Error('研究报告尚未生成。')
  return {
    report_id: `report-${researchId}`, research_id: researchId, result_status: record.job.result_status ?? 'complete',
    claim_ids: ['claim-1', 'claim-2'], evidence_ids: ['ev-alpha', 'ev-beta'], generated_at: now(),
    markdown: `# ${record.job.request.report_spec.title || 'Deep Research 报告'}\n\n## 研究结论\n\nAlpha 与 Beta 的部署状态均为已完成。[E:ev-alpha][E:ev-beta]\n\n## 原文依据\n\n- **Alpha**：部署状态为已完成，验收记录已归档。\n- **Beta**：部署状态为已完成，验收记录已归档。\n\n## 资料限制\n\n本报告仅基于用户审批时冻结的本地资料，不包含范围外信息。`,
  }
}

