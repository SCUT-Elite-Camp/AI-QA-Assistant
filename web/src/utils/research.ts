import type { ResearchJob, ResearchStageDefinition, ResearchStageView } from '../types/research'

export const RESEARCH_STAGES: ResearchStageDefinition[] = [
  { key: 'planning', label: '生成研究计划', description: '分析目标并拆分研究任务', progress: 10 },
  { key: 'awaiting_approval', label: '确认研究计划', description: '等待你确认任务与资料范围', progress: 15 },
  { key: 'ready', label: '等待执行', description: '计划已批准，等待后台领取任务', progress: 20 },
  { key: 'execute_tasks', label: '执行研究任务', description: '搜索并读取冻结资料中的原文', progress: 48 },
  { key: 'coverage', label: '检查资料覆盖度', description: '确认必要问题是否都有证据', progress: 58 },
  { key: 'generate_claims', label: '整理研究结论', description: '从研究发现中生成候选结论', progress: 68 },
  { key: 'structural_verification', label: '检查引用完整性', description: '确认结论引用均可追溯', progress: 76 },
  { key: 'semantic_verification', label: '验证研究结论', description: '核对结论是否得到证据支持', progress: 86 },
  { key: 'render_report', label: '生成研究报告', description: '整理可信结论、引用和限制', progress: 95 },
  { key: 'finalize', label: '完成研究任务', description: '保存报告和最终状态', progress: 98 },
  { key: 'completed', label: '研究已完成', description: '报告已经可以查看', progress: 100 },
]

const stageAliases: Record<string, string> = {
  created: 'planning',
  researching: 'execute_tasks',
  synthesizing: 'render_report',
}

export function normalizedResearchStage(job: ResearchJob): string {
  if (job.status === 'completed') return 'completed'
  if (job.status === 'planning') return 'planning'
  if (job.status === 'awaiting_approval') return 'awaiting_approval'
  if (job.status === 'ready') return 'ready'
  return stageAliases[job.current_stage] ?? job.current_stage
}

export function researchProgress(job: ResearchJob): number {
  if (job.status === 'completed') return 100
  const stage = RESEARCH_STAGES.find(item => item.key === normalizedResearchStage(job))
  if (!stage) return job.status === 'created' ? 2 : 0
  if (stage.key === 'execute_tasks' && job.task_total > 0) {
    const taskRatio = Math.min(job.task_completed / job.task_total, 1)
    return Math.round(20 + taskRatio * 28)
  }
  return stage.progress
}

export function researchStageViews(job: ResearchJob): ResearchStageView[] {
  const current = normalizedResearchStage(job)
  const currentIndex = RESEARCH_STAGES.findIndex(item => item.key === current)
  return RESEARCH_STAGES.filter(item => !['awaiting_approval', 'ready'].includes(item.key) || item.key === current)
    .map((item) => {
      const itemIndex = RESEARCH_STAGES.findIndex(stage => stage.key === item.key)
      let status: ResearchStageView['status'] = 'pending'
      if (itemIndex < currentIndex) status = 'completed'
      if (itemIndex === currentIndex) status = 'running'
      if (job.status === 'completed') status = 'completed'
      if (job.status === 'failed' && item.key === current) status = 'failed'
      return { ...item, status }
    })
}

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

