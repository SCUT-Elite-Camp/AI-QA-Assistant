<script setup lang="ts">
import { computed } from 'vue'
import type { ResearchEvent, ResearchJob, ResearchProgress } from '../../types/research'

const props = defineProps<{ job: ResearchJob, progress: ResearchProgress, events?: ResearchEvent[] }>()
const emit = defineEmits<{ cancel: [] }>()
const activeLabel = computed(() => props.progress.stages.find(item => item.key === props.progress.current_stage)?.label ?? '研究处理中')
const recentEvents = computed(() => [...(props.events ?? [])].reverse().slice(0, 5))
const latestRecovery = computed(() => [...(props.events ?? [])].reverse().find(event => event.event_type === 'job_recovered'))
const elapsedLabel = computed(() => {
  const seconds = Math.round(props.progress.metrics.elapsed_ms / 1000)
  return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
})
</script>

<template>
  <div class="space-y-6">
    <section
      v-if="latestRecovery"
      class="flex items-start gap-3 border-b border-default pb-4"
      role="status"
    >
      <span class="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary"><UIcon name="i-lucide-history" /></span>
      <div>
        <p class="text-sm font-semibold text-highlighted">
          任务已从检查点恢复
        </p>
        <p class="mt-1 text-xs leading-5 text-muted">
          {{ latestRecovery.message }}，已复用此前保存的任务、证据和报告数据。
        </p>
      </div>
    </section>
    <section class="border-b border-default pb-5">
      <div>
        <div class="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p class="text-sm text-muted">
              正在研究
            </p>
            <h2 class="mt-1 text-lg font-semibold text-highlighted">
              {{ activeLabel }}
            </h2>
            <p class="mt-2 text-sm text-muted">
              {{ job.request.query }}
            </p>
          </div>
          <div class="text-right">
            <span class="text-base font-semibold text-highlighted">{{ progress.progress_percent }}%</span><p class="text-xs text-muted">
              整体进度
            </p>
          </div>
        </div>
        <div class="mt-6 h-2 overflow-hidden rounded-full bg-accented">
          <div
            class="h-full rounded-full bg-primary transition-all duration-700"
            :style="{ width: `${progress.progress_percent}%` }"
          />
        </div>
      </div>
    </section>

    <div class="space-y-5">
      <section>
        <h3 class="font-semibold text-highlighted">
          执行流程
        </h3>
        <ol class="mt-5 space-y-0">
          <li
            v-for="(stage, index) in progress.stages"
            :key="stage.key"
            class="relative flex gap-4 pb-5 last:pb-0"
          >
            <div
              v-if="index < progress.stages.length - 1"
              class="absolute left-[13px] top-7 h-full w-px bg-default"
            />
            <span
              class="relative z-10 mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full border"
              :class="stage.status === 'completed' ? 'border-success bg-success text-white' : stage.status === 'running' ? 'border-primary bg-primary text-white ring-4 ring-primary/10' : stage.status === 'failed' ? 'border-error bg-error text-white' : 'border-default bg-default text-muted'"
            >
              <UIcon
                :name="stage.status === 'completed' ? 'i-lucide-check' : stage.status === 'failed' ? 'i-lucide-x' : stage.status === 'running' ? 'i-lucide-loader-circle' : 'i-lucide-circle'"
                :class="{ 'animate-spin': stage.status === 'running' }"
              />
            </span>
            <div>
              <p
                class="text-sm font-medium"
                :class="stage.status === 'pending' ? 'text-muted' : 'text-highlighted'"
              >
                {{ stage.label }}
              </p><p class="mt-0.5 text-xs text-muted">
                {{ stage.completed_at ? '已完成' : stage.started_at ? '执行中' : '等待执行' }}
              </p>
            </div>
          </li>
        </ol>
      </section>

      <div class="space-y-5">
        <section class="border-t border-default pt-5">
          <h3 class="font-semibold text-highlighted">
            研究统计
          </h3>
          <div class="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div class="rounded-lg bg-elevated p-3 text-center">
              <p class="text-xl font-bold text-highlighted">
                {{ progress.task_completed }}/{{ progress.task_total }}
              </p><p class="mt-1 text-xs text-muted">
                任务
              </p>
            </div>
            <div class="rounded-lg bg-elevated p-3 text-center">
              <p class="text-xl font-bold text-highlighted">
                {{ progress.evidence_count }}
              </p><p class="mt-1 text-xs text-muted">
                证据
              </p>
            </div>
            <div class="rounded-lg bg-elevated p-3 text-center">
              <p class="text-xl font-bold text-highlighted">
                {{ progress.claim_count }}
              </p><p class="mt-1 text-xs text-muted">
                结论
              </p>
            </div>
            <div class="rounded-lg bg-elevated p-3 text-center">
              <p class="text-xl font-bold text-highlighted">
                {{ progress.metrics.documents_read }}
              </p><p class="mt-1 text-xs text-muted">
                已读资料
              </p>
            </div>
          </div>
          <dl class="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-default pt-4 text-xs">
            <div>
              <dt class="text-muted">
                已用时间
              </dt><dd class="mt-1 font-medium text-highlighted">
                {{ elapsedLabel }}
              </dd>
            </div>
            <div>
              <dt class="text-muted">
                动作使用
              </dt><dd class="mt-1 font-medium text-highlighted">
                {{ progress.metrics.actions_used }}
              </dd>
            </div>
            <div>
              <dt class="text-muted">
                工具调用
              </dt><dd class="mt-1 font-medium text-highlighted">
                {{ progress.metrics.tool_calls }}
              </dd>
            </div>
            <div>
              <dt class="text-muted">
                恢复次数
              </dt><dd class="mt-1 font-medium text-highlighted">
                {{ progress.metrics.recovery_count }}
              </dd>
            </div>
          </dl>
        </section>

        <section
          v-if="progress.tasks.length"
          class="border-t border-default pt-5"
        >
          <h3 class="font-semibold text-highlighted">
            研究任务
          </h3>
          <ul class="mt-4 space-y-3">
            <li
              v-for="task in progress.tasks"
              :key="task.task_id"
              class="flex items-start gap-3 text-sm"
            >
              <UIcon
                :name="task.status === 'succeeded' ? 'i-lucide-circle-check' : task.status === 'running' ? 'i-lucide-loader-circle' : task.status === 'failed' || task.status === 'blocked' ? 'i-lucide-circle-x' : 'i-lucide-circle'"
                :class="task.status === 'succeeded' ? 'text-success' : task.status === 'running' ? 'animate-spin text-primary' : task.status === 'failed' || task.status === 'blocked' ? 'text-error' : 'text-muted'"
              />
              <span :class="task.status === 'succeeded' ? 'text-muted line-through' : 'text-highlighted'">{{ task.question }}</span>
            </li>
          </ul>
        </section>

        <section
          v-if="recentEvents.length"
          class="border-t border-default pt-5"
        >
          <h3 class="font-semibold text-highlighted">
            最近活动
          </h3>
          <ul class="mt-4 space-y-3">
            <li
              v-for="event in recentEvents"
              :key="event.event_id"
              class="flex items-start gap-3 text-sm"
            >
              <span class="mt-1.5 size-1.5 shrink-0 rounded-full bg-primary" />
              <span class="text-muted">{{ event.message }}</span>
            </li>
          </ul>
        </section>
      </div>
    </div>

    <div class="flex items-center justify-between gap-3 border-t border-default pt-4">
      <p class="text-xs text-muted">
        当前阶段：<span class="font-mono">{{ progress.current_stage }}</span>。页面刷新后会从服务端恢复进度。
      </p>
      <UButton
        v-if="job.status === 'ready'"
        color="error"
        variant="soft"
        size="sm"
        label="取消研究"
        @click="emit('cancel')"
      />
    </div>
  </div>
</template>
