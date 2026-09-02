<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Navbar from '../../components/Navbar.vue'
import ResearchPlanReview from '../../components/research/ResearchPlanReview.vue'
import ResearchProgress from '../../components/research/ResearchProgress.vue'
import ResearchReportView from '../../components/research/ResearchReport.vue'
import { useResearchApi } from '../../composables/useResearchApi'
import { useResearchPolling } from '../../composables/useResearchPolling'
import type { ResearchPlan, ResearchReport } from '../../types/research'
import { formatResearchError } from '../../utils/research'

const route = useRoute()
const router = useRouter()
const api = useResearchApi()
const researchId = computed(() => String((route.params as { id?: string }).id ?? ''))
const plan = ref<ResearchPlan | null>(null)
const report = ref<ResearchReport | null>(null)
const actionLoading = ref(false)
const actionError = ref('')

const { job, loading, error: pollingError, restart, stop } = useResearchPolling(() => api.getJob(researchId.value))

watch(() => job.value?.status, async (status) => {
  if (!status) return
  if (['awaiting_approval', 'ready', 'researching', 'synthesizing', 'completed'].includes(status) && !plan.value) {
    try { plan.value = await api.getPlan(researchId.value) } catch { /* planning may not have persisted the plan yet */ }
  }
  if (status === 'completed' && !report.value) {
    try { report.value = await api.getReport(researchId.value) } catch (reason) { actionError.value = formatResearchError(reason) }
  }
}, { immediate: true })

async function approve() {
  if (!plan.value?.manifest_hash) return
  actionLoading.value = true
  actionError.value = ''
  try {
    job.value = await api.approveJob(researchId.value, { plan_version: plan.value.version, manifest_hash: plan.value.manifest_hash })
    restart()
  } catch (reason) { actionError.value = formatResearchError(reason) } finally { actionLoading.value = false }
}

async function cancel() {
  actionLoading.value = true
  actionError.value = ''
  try { job.value = await api.cancelJob(researchId.value); stop() }
  catch (reason) { actionError.value = formatResearchError(reason) }
  finally { actionLoading.value = false }
}

const statusTitle = computed(() => {
  const status = job.value?.status
  if (status === 'awaiting_approval') return '确认研究计划'
  if (status === 'completed') return '研究报告'
  if (status === 'failed') return '研究执行失败'
  if (status === 'cancelled') return '研究已取消'
  return 'Deep Research'
})
</script>

<template>
  <UDashboardPanel
    id="research-detail"
    class="min-h-0 w-full"
    :ui="{ body: 'p-0 sm:p-0' }"
  >
    <template #header>
      <Navbar>
        <template #title>
          <div class="flex min-w-0 items-center gap-2">
            <UIcon
              name="i-lucide-telescope"
              class="shrink-0 text-primary"
            /><span class="truncate font-semibold">{{ statusTitle }}</span>
          </div>
        </template>
      </Navbar>
    </template>
    <template #body>
      <UContainer class="w-full max-w-5xl py-10 sm:py-14">
        <div
          v-if="loading"
          class="flex min-h-80 flex-col items-center justify-center gap-4 text-muted"
        >
          <UIcon
            name="i-lucide-loader-circle"
            class="size-8 animate-spin text-primary"
          /><p>正在恢复 Research Job…</p>
        </div>

        <div
          v-else-if="pollingError && !job"
          class="mx-auto max-w-lg rounded-xl border border-error/30 bg-error/5 p-6 text-center"
        >
          <UIcon
            name="i-lucide-circle-alert"
            class="mx-auto size-8 text-error"
          /><h2 class="mt-3 font-semibold text-highlighted">
            无法加载研究任务
          </h2><p class="mt-2 text-sm text-muted">
            {{ formatResearchError(pollingError) }}
          </p><div class="mt-5 flex justify-center gap-2">
            <UButton
              to="/research/new"
              color="neutral"
              variant="soft"
              label="新建研究"
            /><UButton
              label="重试"
              @click="restart"
            />
          </div>
        </div>

        <template v-else-if="job">
          <div
            v-if="actionError"
            class="mb-5 flex gap-2 rounded-lg border border-error/30 bg-error/5 p-3 text-sm text-error"
          >
            <UIcon
              name="i-lucide-circle-alert"
              class="mt-0.5 shrink-0"
            /><span>{{ actionError }}</span>
          </div>

          <div
            v-if="['created', 'planning'].includes(job.status)"
            class="flex min-h-80 flex-col items-center justify-center text-center"
          >
            <span class="flex size-16 items-center justify-center rounded-full bg-primary/10"><UIcon
              name="i-lucide-sparkles"
              class="size-7 animate-pulse text-primary"
            /></span><h1 class="mt-5 text-2xl font-bold text-highlighted">
              正在生成研究计划
            </h1><p class="mt-3 max-w-lg text-sm leading-6 text-muted">
              系统正在冻结资料快照、拆分研究任务并检查计划约束。完成后需要你确认才会开始研究。
            </p>
          </div>

          <ResearchPlanReview
            v-else-if="job.status === 'awaiting_approval' && plan"
            :plan="plan"
            :approving="actionLoading"
            @approve="approve"
            @cancel="cancel"
          />

          <ResearchProgress
            v-else-if="['ready', 'researching', 'synthesizing'].includes(job.status)"
            :job="job"
            :plan="plan"
            @cancel="cancel"
          />

          <ResearchReportView
            v-else-if="job.status === 'completed' && report"
            :job="job"
            :report="report"
            @restart="router.push('/research/new')"
          />

          <div
            v-else-if="job.status === 'completed'"
            class="flex min-h-80 flex-col items-center justify-center gap-3 text-muted"
          >
            <UIcon
              name="i-lucide-loader-circle"
              class="size-7 animate-spin text-primary"
            /><p>正在加载研究报告…</p>
          </div>

          <div
            v-else-if="job.status === 'failed'"
            class="mx-auto max-w-xl rounded-xl border border-error/30 bg-error/5 p-8 text-center"
          >
            <UIcon
              name="i-lucide-octagon-alert"
              class="mx-auto size-10 text-error"
            /><h1 class="mt-4 text-2xl font-bold text-highlighted">
              研究执行失败
            </h1><p class="mt-3 text-sm text-muted">
              失败阶段：{{ job.failure_stage || job.current_stage }}
            </p><code class="mt-3 inline-block rounded bg-default px-3 py-1 text-xs text-error">{{ job.error_code || 'research_failed' }}</code><div class="mt-6 flex justify-center gap-2">
              <UButton
                to="/research/new"
                color="neutral"
                variant="soft"
                label="新建研究"
              /><UButton
                label="重新加载"
                @click="restart"
              />
            </div>
          </div>

          <div
            v-else-if="job.status === 'cancelled'"
            class="mx-auto max-w-xl rounded-xl border border-default bg-elevated/30 p-8 text-center"
          >
            <UIcon
              name="i-lucide-circle-slash"
              class="mx-auto size-10 text-muted"
            /><h1 class="mt-4 text-2xl font-bold text-highlighted">
              研究已取消
            </h1><p class="mt-3 text-sm text-muted">
              已保留取消前的任务状态和资料快照。
            </p><UButton
              class="mt-6"
              to="/research/new"
              label="发起新的研究"
            />
          </div>
        </template>
      </UContainer>
    </template>
  </UDashboardPanel>
</template>
