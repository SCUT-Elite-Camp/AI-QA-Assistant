<script setup lang="ts">
import { computed, nextTick, provide, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { $fetch } from 'ofetch'
import Navbar from '../../components/Navbar.vue'
import ResearchPlanReview from '../../components/research/ResearchPlanReview.vue'
import ResearchReportView from '../../components/research/ResearchReport.vue'
import ResearchStatusCard from '../../components/research/ResearchStatusCard.vue'
import ChatComark from '../../components/chat/Comark'
import ResearchMessageActions from '../../components/research/ResearchMessageActions.vue'
import type { ChunkCitation } from '../../components/chat/tool/Sources.vue'
import { useResearchApi } from '../../composables/useResearchApi'
import { useResearchPolling } from '../../composables/useResearchPolling'
import { useChats } from '../../composables/useChats'
import { useCsrf } from '../../composables/useCsrf'
import type { ResearchPlan, ResearchPlanRevisionRequest, ResearchReport } from '../../types/research'
import { formatResearchError } from '../../utils/research'

const route = useRoute()
const router = useRouter()
const api = useResearchApi()
const { fetchChats } = useChats()
const { csrf, headerName } = useCsrf()
const researchId = computed(() => String((route.params as { id?: string }).id ?? ''))
const plan = ref<ResearchPlan | null>(null)
const report = ref<ResearchReport | null>(null)
const actionLoading = ref(false)
const actionError = ref('')
const conversationInput = ref('')
const conversationInputRef = ref<HTMLTextAreaElement | null>(null)
let planLoadInFlight = false
let reportLoadInFlight = false
let chatRegistrationInFlight = false

const { job, progress, events, loading, error: pollingError, restart, stop } = useResearchPolling(
  () => api.getJob(researchId.value),
  () => api.getProgress(researchId.value),
  afterEventId => api.getEvents(researchId.value, afterEventId),
)

watch(job, async (nextJob) => {
  const status = nextJob?.status
  if (!status) return
  if (!chatRegistrationInFlight) {
    chatRegistrationInFlight = true
    try {
      await $fetch('/api/research/chats', {
        method: 'POST',
        headers: { [headerName]: csrf() },
        body: { researchId: nextJob.research_id, query: nextJob.request.query },
      })
      await fetchChats()
    } catch { /* Research remains usable if sidebar persistence is temporarily unavailable. */ }
  }
  if (['awaiting_approval', 'ready', 'researching', 'synthesizing', 'completed'].includes(status) && !plan.value && !planLoadInFlight) {
    planLoadInFlight = true
    try { plan.value = await api.getPlan(researchId.value) } catch { /* polling retries after transient failures */ } finally { planLoadInFlight = false }
  }
  if (status === 'completed' && !report.value && !reportLoadInFlight) {
    reportLoadInFlight = true
    try { report.value = await api.getReport(researchId.value) } catch (reason) { actionError.value = formatResearchError(reason) } finally { reportLoadInFlight = false }
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

async function revise(revision: ResearchPlanRevisionRequest) {
  actionLoading.value = true
  actionError.value = ''
  try {
    plan.value = await api.revisePlan(researchId.value, revision)
    job.value = await api.getJob(researchId.value)
    restart()
  } catch (reason) { actionError.value = formatResearchError(reason) } finally { actionLoading.value = false }
}

async function cancel() {
  actionLoading.value = true
  actionError.value = ''
  try {
    job.value = await api.cancelJob(researchId.value)
    progress.value = await api.getProgress(researchId.value)
    stop()
  }
  catch (reason) { actionError.value = formatResearchError(reason) }
  finally { actionLoading.value = false }
}

async function sendConversationMessage(override?: string) {
  const message = (override ?? conversationInput.value).trim()
  if (!message || actionLoading.value) return
  conversationInput.value = ''
  actionLoading.value = true
  actionError.value = ''
  try {
    const response = await api.sendMessage(researchId.value, message)
    job.value = response.job
    if (response.plan) plan.value = response.plan
    if (response.action === 'conflict_resolved') report.value = await api.getReport(researchId.value)
    restart()
  } catch (reason) {
    actionError.value = formatResearchError(reason)
    conversationInput.value = message
  } finally {
    actionLoading.value = false
  }
}

function regenerateConversationEvent(eventId: number) {
  const index = events.value.findIndex(event => event.event_id === eventId)
  const previousUser = [...events.value.slice(0, index)].reverse().find(event => event.event_type === 'user_message')
  if (previousUser) void sendConversationMessage(previousUser.message)
}

function regenerateReport() {
  void sendConversationMessage('请基于当前已核验的证据重新生成一份结构更完整、表达更清晰的研究回答，并保留可追踪引用。')
}

async function askAboutSelectedText(text: string) {
  conversationInput.value = `关于“${text}”：`
  await nextTick()
  conversationInputRef.value?.focus()
}

const conversationEvents = computed(() => events.value.filter(event =>
  ['user_message', 'assistant_message'].includes(event.event_type),
))
const citationMap = computed(() => new Map<number, ChunkCitation>((report.value?.citations ?? []).map(citation => [
  citation.number,
  {
    index: citation.number,
    doc_id: citation.doc_id,
    chunk_id: citation.evidence_id,
    title: citation.title,
    source_url: citation.source_url ?? undefined,
    chunk_text: citation.excerpt,
  },
])))

provide('ragCitationMap', citationMap)

function conversationMarkdown(message: string) {
  return message.replace(/\[(\d+)]/g, '<cite-mark index="$1"></cite-mark>')
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
      <div class="flex h-full min-h-0 flex-col">
        <div class="min-h-0 flex-1 overflow-y-auto">
          <UContainer class="w-full max-w-6xl py-6 sm:py-10">
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
                  to="/"
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

              <div class="grid items-start gap-10 lg:grid-cols-[minmax(0,1fr)_280px]">
                <main class="min-w-0 space-y-8">
                  <div class="flex justify-end">
                    <div class="max-w-[85%] rounded-3xl bg-elevated px-5 py-3 text-sm leading-6 text-highlighted sm:max-w-[75%]">
                      {{ job.request.query }}
                    </div>
                  </div>

                  <div
                    v-if="plan && ['ready', 'researching', 'synthesizing', 'completed'].includes(job.status)"
                    class="flex items-start gap-3"
                  >
                    <span class="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full border border-default bg-default">
                      <UIcon
                        name="i-lucide-telescope"
                        class="size-4 text-primary"
                      />
                    </span>
                    <div class="max-w-2xl py-1 text-sm leading-6">
                      <p class="font-semibold text-highlighted">
                        研究计划已确认
                      </p>
                      <p class="mt-1 text-muted">
                        我会按照计划 v{{ plan.version }} 完成 {{ plan.tasks.length }} 个任务，并持续保存执行状态。
                      </p>
                    </div>
                  </div>

                  <div class="flex items-start gap-3">
                    <span class="mt-1 flex size-8 shrink-0 items-center justify-center rounded-full border border-default bg-default">
                      <UIcon
                        name="i-lucide-telescope"
                        class="size-4 text-primary"
                      />
                    </span>
                    <div class="min-w-0 flex-1">
                      <div
                        v-if="['created', 'planning'].includes(job.status)"
                        class="py-2"
                      >
                        <div class="flex items-center gap-3 text-sm text-highlighted">
                          <UIcon
                            name="i-lucide-loader-circle"
                            class="size-4 animate-spin text-primary"
                          />
                          <span>我正在整理资料范围并生成研究计划。</span>
                        </div>
                        <p class="mt-2 text-sm leading-6 text-muted">
                          计划生成后会先发给你确认，在你批准前不会开始检索。
                        </p>
                      </div>

                      <ResearchPlanReview
                        v-else-if="job.status === 'awaiting_approval' && plan"
                        :plan="plan"
                        :approving="actionLoading"
                        :revising="actionLoading"
                        @approve="approve"
                        @cancel="cancel"
                        @revise="revise"
                      />

                      <div
                        v-else-if="['ready', 'researching', 'synthesizing'].includes(job.status) && progress"
                        class="py-2"
                        role="status"
                      >
                        <div class="flex items-center gap-2 text-sm text-highlighted">
                          <UIcon
                            name="i-lucide-loader-circle"
                            class="size-4 animate-spin text-primary"
                          />
                          <span>研究正在进行，详细进度可以在右侧状态栏查看。</span>
                        </div>
                        <UButton
                          v-if="job.status === 'ready'"
                          class="mt-3"
                          color="neutral"
                          variant="ghost"
                          size="sm"
                          label="取消研究"
                          @click="cancel"
                        />
                      </div>

                      <ResearchReportView
                        v-else-if="job.status === 'completed' && report"
                        :job="job"
                        :report="report"
                        :plan="plan"
                        :progress="progress"
                        :events="events"
                        @restart="router.push('/')"
                        @ask-selected-text="askAboutSelectedText"
                        @regenerate="regenerateReport"
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
                          失败阶段：{{ progress?.error?.stage || job.failure_stage || job.current_stage }}
                        </p><p class="mt-3 text-sm text-error">
                          {{ progress?.error?.message || '研究任务执行失败，请稍后重试。' }}
                        </p><div class="mt-6 flex justify-center gap-2">
                          <UButton
                            to="/"
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
                          to="/"
                          label="发起新的研究"
                        />
                      </div>

                      <div
                        v-if="conversationEvents.length"
                        class="mt-8 space-y-5"
                      >
                        <div
                          v-for="event in conversationEvents"
                          :key="event.event_id"
                          :class="event.event_type === 'user_message' ? 'flex justify-end' : 'flex items-start gap-3'"
                        >
                          <span
                            v-if="event.event_type === 'assistant_message'"
                            class="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full border border-default bg-default"
                          >
                            <UIcon
                              name="i-lucide-telescope"
                              class="size-4 text-primary"
                            />
                          </span>
                          <p
                            v-if="event.event_type === 'user_message'"
                            class="max-w-[75%] rounded-3xl bg-elevated px-5 py-3 text-sm leading-6 text-highlighted"
                          >
                            {{ event.message }}
                          </p>
                          <div
                            v-else
                            class="max-w-2xl py-1 text-sm leading-6 text-highlighted"
                          >
                            <ChatComark
                              :markdown="conversationMarkdown(event.message)"
                              :streaming="false"
                            />
                            <ResearchMessageActions
                              :chat-id="researchId"
                              :message-id="`research-event-${event.event_id}`"
                              :text="event.message"
                              :created-at="event.created_at"
                              @regenerate="regenerateConversationEvent(event.event_id)"
                            />
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </main>

                <div class="sticky top-20 hidden lg:block">
                  <ResearchStatusCard
                    :job="job"
                    :progress="progress"
                    :events="events"
                  />
                </div>
                <div class="order-first lg:hidden">
                  <ResearchStatusCard
                    :job="job"
                    :progress="progress"
                    :events="events"
                  />
                </div>
              </div>
            </template>
          </UContainer>
        </div>

        <div
          v-if="job && !['failed', 'cancelled'].includes(job.status)"
          class="shrink-0 border-t border-default bg-default"
        >
          <UContainer class="w-full max-w-6xl py-3 sm:py-4">
            <div class="grid gap-10 lg:grid-cols-[minmax(0,1fr)_280px]">
              <form
                class="flex min-w-0 items-end gap-2 rounded-2xl border border-default bg-default p-2 shadow-lg"
                @submit.prevent="sendConversationMessage"
              >
                <textarea
                  ref="conversationInputRef"
                  v-model="conversationInput"
                  rows="1"
                  :placeholder="job.status === 'awaiting_approval' ? '回复“批准”，或直接描述要修改的步骤…' : job.status === 'completed' && report?.conflicts?.some(conflict => conflict.resolution_status === 'unresolved') ? '回复“采用来源 2”，或说明你的处理意见…' : '继续询问这项研究…'"
                  class="min-h-11 min-w-0 flex-1 resize-none bg-transparent px-3 py-2.5 text-base leading-6 text-highlighted outline-none placeholder:text-muted"
                  aria-label="研究对话消息"
                  @keydown.enter.exact.prevent="sendConversationMessage"
                />
                <UButton
                  type="submit"
                  icon="i-lucide-arrow-up"
                  color="neutral"
                  :loading="actionLoading"
                  :disabled="!conversationInput.trim() || actionLoading"
                  aria-label="发送研究消息"
                  class="rounded-full"
                />
              </form>
            </div>
          </UContainer>
        </div>
      </div>
    </template>
  </UDashboardPanel>
</template>
