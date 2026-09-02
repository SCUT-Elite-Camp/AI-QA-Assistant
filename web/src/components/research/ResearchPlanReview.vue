<script setup lang="ts">
import type { ResearchPlan } from '../../types/research'

defineProps<{ plan: ResearchPlan, approving?: boolean }>()
const emit = defineEmits<{ approve: [], cancel: [] }>()
</script>

<template>
  <div class="space-y-6">
    <div class="rounded-xl border border-primary/25 bg-primary/5 p-5">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p class="text-xs font-semibold uppercase tracking-wider text-primary">
            等待你的确认
          </p>
          <h2 class="mt-1 text-xl font-bold text-highlighted">
            研究计划 v{{ plan.version }}
          </h2>
        </div>
        <UBadge
          color="primary"
          variant="soft"
          :label="`${plan.tasks.length} 个任务`"
        />
      </div>
      <p class="mt-4 text-sm leading-6 text-muted">
        {{ plan.objective }}
      </p>
    </div>

    <div class="space-y-3">
      <article
        v-for="(task, index) in plan.tasks"
        :key="task.task_id"
        class="rounded-xl border border-default bg-default p-4 shadow-sm"
      >
        <div class="flex items-start gap-3">
          <span class="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">{{ index + 1 }}</span>
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <h3 class="font-semibold text-highlighted">
                {{ task.question }}
              </h3>
              <UBadge
                v-if="task.priority === 'critical'"
                color="warning"
                variant="soft"
                label="关键任务"
                size="sm"
              />
            </div>
            <p class="mt-1 text-sm text-muted">
              {{ task.purpose }}
            </p>
            <div class="mt-3 flex flex-wrap gap-2 text-xs text-muted">
              <span class="rounded-md bg-elevated px-2 py-1">{{ task.task_id }}</span>
              <span
                v-if="task.dependencies.length"
                class="rounded-md bg-elevated px-2 py-1"
              >依赖：{{ task.dependencies.join(', ') }}</span>
              <span class="rounded-md bg-elevated px-2 py-1">最多 {{ task.max_actions }} 次动作</span>
            </div>
            <ul class="mt-3 space-y-1 text-xs text-muted">
              <li
                v-for="criterion in task.acceptance_criteria"
                :key="criterion.criterion_id"
                class="flex gap-2"
              >
                <UIcon
                  name="i-lucide-check-circle-2"
                  class="mt-0.5 shrink-0 text-primary"
                />
                <span>{{ criterion.target }}</span>
              </li>
            </ul>
          </div>
        </div>
      </article>
    </div>

    <div class="grid gap-3 rounded-xl border border-default bg-elevated/30 p-4 text-sm sm:grid-cols-3">
      <div>
        <p class="text-xs text-muted">
          计划版本
        </p><p class="mt-1 font-medium">
          v{{ plan.version }}
        </p>
      </div>
      <div>
        <p class="text-xs text-muted">
          最大运行时间
        </p><p class="mt-1 font-medium">
          {{ plan.budget.max_runtime_seconds }} 秒
        </p>
      </div>
      <div>
        <p class="text-xs text-muted">
          资料快照
        </p><p
          class="mt-1 truncate font-mono text-xs"
          :title="plan.manifest_hash || ''"
        >
          {{ plan.manifest_hash }}
        </p>
      </div>
    </div>

    <div class="flex flex-wrap items-center justify-between gap-3 border-t border-default pt-5">
      <p class="max-w-xl text-xs leading-5 text-muted">
        批准后，系统只会使用该资料快照和计划版本执行。资料发生变化时需要重新确认。
      </p>
      <div class="flex gap-2">
        <UButton
          color="neutral"
          variant="ghost"
          label="取消任务"
          @click="emit('cancel')"
        />
        <UButton
          icon="i-lucide-check"
          label="批准并开始研究"
          :loading="approving"
          :disabled="approving"
          @click="emit('approve')"
        />
      </div>
    </div>
  </div>
</template>

