<script setup lang="ts">
import { computed } from 'vue'
import type { ResearchEvent, ResearchJob, ResearchProgress } from '../../types/research'

const props = defineProps<{ job: ResearchJob, progress?: ResearchProgress | null, events?: ResearchEvent[] }>()

const statusLabel = computed(() => ({
  created: '准备研究',
  planning: '生成计划',
  awaiting_approval: '等待审批',
  ready: '等待执行',
  researching: '检索与核验',
  synthesizing: '整理报告',
  completed: '研究完成',
  failed: '执行失败',
  cancelled: '已取消',
}[props.job.status] ?? '处理中'))

const percent = computed(() => props.progress?.progress_percent ?? (props.job.status === 'completed' ? 100 : 10))
const recentEvents = computed(() => [...(props.events ?? [])].reverse().slice(0, 6))
</script>

<template>
  <aside
    class="border-b border-default bg-default px-1 pb-4 lg:border-b-0 lg:border-l lg:px-5 lg:py-4"
    aria-label="研究活动"
  >
    <div class="flex items-center justify-between gap-3">
      <div class="flex items-center gap-2">
        <UIcon
          name="i-lucide-telescope"
          class="size-4 text-primary"
        />
        <span class="text-sm font-semibold text-highlighted">研究活动</span>
      </div>
      <span class="text-xs tabular-nums text-muted">{{ percent }}%</span>
    </div>
    <p class="mt-5 text-sm font-medium text-highlighted">
      {{ statusLabel }}
    </p>
    <div class="mt-2 h-1 overflow-hidden rounded-full bg-accented">
      <div
        class="h-full rounded-full bg-primary transition-[width] duration-500"
        :style="{ width: `${percent}%` }"
      />
    </div>
    <div
      v-if="progress"
      class="mt-3 flex gap-4 text-xs text-muted"
    >
      <span>{{ progress.task_completed }}/{{ progress.task_total }} 任务</span>
      <span>{{ progress.evidence_count }} 证据</span>
    </div>
    <ol
      v-if="progress?.stages?.length"
      class="mt-5 hidden space-y-3 border-t border-default pt-4 lg:block"
    >
      <li
        v-for="stage in progress.stages"
        :key="stage.key"
        class="flex items-start gap-2 text-xs"
      >
        <UIcon
          :name="stage.status === 'completed' ? 'i-lucide-check' : stage.status === 'running' ? 'i-lucide-loader-circle' : 'i-lucide-circle'"
          :class="stage.status === 'completed' ? 'text-success' : stage.status === 'running' ? 'animate-spin text-primary' : 'text-muted'"
          class="mt-0.5 size-3.5 shrink-0"
        />
        <span :class="stage.status === 'pending' ? 'text-muted' : 'text-highlighted'">{{ stage.label }}</span>
      </li>
    </ol>
    <div
      v-if="recentEvents.length"
      class="mt-5 hidden border-t border-default pt-4 lg:block"
    >
      <p class="text-xs font-medium text-highlighted">
        最近活动
      </p>
      <p
        v-for="event in recentEvents"
        :key="event.event_id"
        class="mt-2 text-[11px] leading-4 text-muted"
      >
        {{ event.message }}
      </p>
    </div>
    <p class="mt-4 hidden text-[11px] leading-4 text-muted lg:block">
      状态已保存，刷新页面后可继续。
    </p>
  </aside>
</template>
