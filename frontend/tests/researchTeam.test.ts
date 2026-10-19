// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ResearchPlanReview from '../src/components/research/ResearchPlanReview.vue'
import ResearchTeamStatus from '../src/components/research/ResearchTeamStatus.vue'
import type { ResearchPlan, ResearchTeamSummary } from '../src/types/research'

function plan(): ResearchPlan {
  return {
    schema_version: 'research.v2', research_id: 'research-team', version: 1,
    objective: 'Compare documented access procedures.', source_scope: { document_ids: ['alpha', 'beta'], knowledge_base_ids: [], topic: '' },
    report_spec: { format: 'markdown', language: 'en-US', title: '', sections: [], include_citations: true, include_limitations: true },
    manifest_hash: 'manifest-hash', status: 'awaiting_approval', execution_mode: 'coordinator',
    source_files: [{ doc_id: 'alpha', title: 'Alpha access guide', version: '1' }, { doc_id: 'beta', title: 'Beta access guide', version: '2' }],
    budget: { max_tasks: 6, max_actions: 64, max_tool_calls: 64, max_tokens: 64000, max_runtime_seconds: 900, max_parallel_agents: 3 },
    tasks: ['alpha', 'beta'].map((name, i) => ({ task_id: `task-${i + 1}`, question: `Check ${name} access.`,
      purpose: 'Establish native permission requirements.', dependencies: [], source_ids: [name],
      allowed_tools: ['keyword_search', 'read_document_range'], max_actions: 6, priority: 'normal', status: 'pending',
      acceptance_criteria: [{ criterion_id: `criterion-${i + 1}`, dimension: 'evidence', target: 'Verify the documented permission check.',
        description: '', requires_evidence: true, required: true }] })),
  }
}

describe('coordinator research plan and review', () => {
  it('keeps independent tasks parallel when the human reorders and saves the plan', async () => {
    const wrapper = mount(ResearchPlanReview, { props: { plan: plan() }, global: { stubs: {
      UBadge: true, UIcon: true,
      UButton: { props: ['label', 'disabled'], emits: ['click'], template: '<button :disabled="disabled" @click="$emit(\'click\')">{{ label }}</button>' },
    } } })
    expect(wrapper.text()).toContain('Alpha access guide')
    expect(wrapper.text()).toContain('independent reviewer')
    await wrapper.findAll('button').find(b => b.text() === 'Edit plan')!.trigger('click')
    await wrapper.find('button[aria-label="Move task down"]').trigger('click')
    await wrapper.findAll('label').find(label => label.text().includes('Evidence required to answer'))!.find('textarea').setValue('Verify current native permission and the effective date.')
    await wrapper.findAll('button').find(b => b.text() === 'Save new version')!.trigger('click')
    const revision = wrapper.emitted('revise')![0]![0] as { base_version: number, tasks: ResearchPlan['tasks'] }
    expect(revision.base_version).toBe(1)
    expect(revision.tasks.map(t => t.task_id)).toEqual(['task-2', 'task-1'])
    expect(revision.tasks.every(t => t.dependencies.length === 0)).toBe(true)
    expect(revision.tasks[0]!.acceptance_criteria[0]!.target).toContain('effective date')
    expect(revision.tasks[0]!.acceptance_criteria[0]!.description).toContain('effective date')
    expect(wrapper.emitted('approve')).toBeUndefined()
    wrapper.unmount()
  })

  it('shows a rejected draft and correction advice separately from its passed revision', () => {
    const team: ResearchTeamSummary = {
      agents: [], completion_tokens_used: 1000,
      drafts: [1, 2].map(revision => ({ draft_id: `draft-${revision}`, revision, author_agent_id: `author-${revision}`,
        report_hash: `hash-${revision}`, review_status: revision === 1 ? 'not_passed' : 'passed' })),
      reviews: [{ review_id: 'review-1', revision: 1, reviewer_agent_id: 'reviewer-1', status: 'not_passed',
        issues: [{ issue_id: 'issue-1', description: 'Availability was not established.', suggestion: 'Use only the documented permission requirement.' }] }],
    }
    const wrapper = mount(ResearchTeamStatus, { props: { team } })
    expect(wrapper.text()).toContain('Not passed — revision required')
    expect(wrapper.text()).toContain('Report revision 2 · Review passed')
    expect(wrapper.text()).toContain('Use only the documented permission requirement.')
    wrapper.unmount()
  })
})
