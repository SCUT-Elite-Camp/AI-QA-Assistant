<script setup lang="ts">
import { computed } from 'vue'
import type { ResearchEvent, ResearchJob, ResearchProgress } from '../../types/research'

const props = defineProps<{ job: ResearchJob, progress: ResearchProgress, events?: ResearchEvent[] }>()
const emit = defineEmits<{ cancel: [] }>()
const activeLabel = computed(() => props.progress.stages.find(item => item.key === props.progress.current_stage)?.label ?? '研究处理中')
const recentEvents = computed(() => [...(props.events ?? [])].reverse().slice(0, 5))
</script>

<template>
  <div class="space-y-6">
    <section class="overflow-hidden rounded-2xl border border-default bg-default shadow-sm">
      <div class="bg-gradient-to-br from-primary/10 via-default to-default p-6 sm:p-8">
        <div class="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p class="text-xs font-semibold uppercase tracking-wider text-primary">
              Deep Research 正在执行
            </p>
            <h2 class="mt-2 text-2xl font-bold text-highlighted">
              {{ activeLabel }}
            </h2>
            <p class="mt-2 text-sm text-muted">
              {{ job.request.query }}
            </p>
          </div>
          <div class="text-right">
            <span class="text-3xl font-bold text-primary">{{ progress.progress_percent }}%</span><p class="text-xs text-muted">
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

    <div class="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
      <section class="rounded-xl border border-default bg-default p-5">
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

      <div class="space-y-6">
        <section class="rounded-xl border border-default bg-default p-5">
          <h3 class="font-semibold text-highlighted">
            研究统计
          </h3>
          <div class="mt-4 grid grid-cols-3 gap-3">
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
          </div>
        </section>

        <section
          v-if="progress.tasks.length"
          class="rounded-xl border border-default bg-default p-5"
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
          class="rounded-xl border border-default bg-default p-5"
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

    <div class="flex items-center justify-between gap-3 rounded-xl border border-default bg-elevated/30 p-4">
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
