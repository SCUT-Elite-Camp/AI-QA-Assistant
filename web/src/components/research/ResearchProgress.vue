<script setup lang="ts">
import { computed } from 'vue'
import type { ResearchJob, ResearchPlan } from '../../types/research'
import { normalizedResearchStage, researchProgress, researchStageViews } from '../../utils/research'

const props = defineProps<{ job: ResearchJob, plan?: ResearchPlan | null }>()
const emit = defineEmits<{ cancel: [] }>()
const progress = computed(() => researchProgress(props.job))
const stages = computed(() => researchStageViews(props.job))
const activeLabel = computed(() => stages.value.find(item => item.status === 'running')?.label ?? '研究处理中')
const tasks = computed(() => props.plan?.tasks ?? [])
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
            <span class="text-3xl font-bold text-primary">{{ progress }}%</span><p class="text-xs text-muted">
              整体进度
            </p>
          </div>
        </div>
        <div class="mt-6 h-2 overflow-hidden rounded-full bg-accented">
          <div
            class="h-full rounded-full bg-primary transition-all duration-700"
            :style="{ width: `${progress}%` }"
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
            v-for="(stage, index) in stages"
            :key="stage.key"
            class="relative flex gap-4 pb-5 last:pb-0"
          >
            <div
              v-if="index < stages.length - 1"
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
                {{ stage.description }}
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
                {{ job.task_completed }}/{{ job.task_total }}
              </p><p class="mt-1 text-xs text-muted">
                任务
              </p>
            </div>
            <div class="rounded-lg bg-elevated p-3 text-center">
              <p class="text-xl font-bold text-highlighted">
                {{ job.evidence_count }}
              </p><p class="mt-1 text-xs text-muted">
                证据
              </p>
            </div>
            <div class="rounded-lg bg-elevated p-3 text-center">
              <p class="text-xl font-bold text-highlighted">
                {{ job.claim_count ?? '—' }}
              </p><p class="mt-1 text-xs text-muted">
                结论
              </p>
            </div>
          </div>
        </section>

        <section
          v-if="tasks.length"
          class="rounded-xl border border-default bg-default p-5"
        >
          <h3 class="font-semibold text-highlighted">
            研究任务
          </h3>
          <ul class="mt-4 space-y-3">
            <li
              v-for="(task, index) in tasks"
              :key="task.task_id"
              class="flex items-start gap-3 text-sm"
            >
              <UIcon
                :name="index < job.task_completed ? 'i-lucide-circle-check' : job.current_task_id === task.task_id ? 'i-lucide-loader-circle' : 'i-lucide-circle'"
                :class="index < job.task_completed ? 'text-success' : job.current_task_id === task.task_id ? 'animate-spin text-primary' : 'text-muted'"
              />
              <span :class="index < job.task_completed ? 'text-muted line-through' : 'text-highlighted'">{{ task.question }}</span>
            </li>
          </ul>
        </section>
      </div>
    </div>

    <div class="flex items-center justify-between gap-3 rounded-xl border border-default bg-elevated/30 p-4">
      <p class="text-xs text-muted">
        当前阶段：<span class="font-mono">{{ normalizedResearchStage(job) }}</span>。页面刷新后会从服务端恢复进度。
      </p>
      <UButton
        color="error"
        variant="soft"
        size="sm"
        label="取消研究"
        @click="emit('cancel')"
      />
    </div>
  </div>
</template>

