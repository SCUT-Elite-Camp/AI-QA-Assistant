<script setup lang="ts">
import type { ResearchTeamSummary } from '../../types/research'
defineProps<{ team: ResearchTeamSummary }>()
</script>

<template>
  <section class="my-5 space-y-4 rounded-xl border border-default p-4" aria-label="Research team and review">
    <h3 class="font-semibold text-highlighted">Exploration and review</h3>
    <p class="text-xs text-muted">Completion tokens charged: {{ team.completion_tokens_used.toLocaleString() }}</p>
    <ul v-if="team.agents.length" class="space-y-2 text-sm text-muted">
      <li v-for="agent in team.agents" :key="agent.agent_id">
        {{ agent.role === 'repair' ? 'Revision agent' : 'Explorer' }} · {{ agent.task_id }} · {{ agent.status }}
        <span v-if="agent.missing.length"> · {{ agent.missing.length }} unresolved items</span>
      </li>
    </ul>
    <p v-if="!team.drafts.length" class="text-sm text-muted">The coordinator will assemble the explorers’ results before independent review.</p>
    <div v-for="draft in team.drafts" :key="draft.draft_id" class="text-sm">
      <p class="font-medium text-highlighted">Report revision {{ draft.revision }} · {{ draft.review_status === 'passed' ? 'Review passed' : draft.review_status === 'not_passed' ? 'Not passed — revision required' : 'Awaiting independent review' }}</p>
      <ul v-for="review in team.reviews.filter(r => r.revision === draft.revision)" :key="review.review_id" class="mt-2 space-y-2 text-muted">
        <li v-for="issue in review.issues" :key="issue.issue_id">
          <p>{{ issue.description }}</p>
          <p class="mt-1">Suggested correction: {{ issue.suggestion }}</p>
        </li>
      </ul>
    </div>
    <p class="text-xs text-muted">A report is released only after its exact revision passes independent review and the coordinator’s final check.</p>
  </section>
</template>
