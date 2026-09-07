<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { ResearchPlan, ResearchPlanRevisionRequest, ResearchTask } from '../../types/research'

const props = defineProps<{ plan: ResearchPlan, approving?: boolean, revising?: boolean }>()
const emit = defineEmits<{ approve: [], cancel: [], revise: [revision: ResearchPlanRevisionRequest] }>()

const editing = ref(false)
const objective = ref('')
const tasks = ref<ResearchTask[]>([])
const revisionNote = ref('')
const validationError = ref('')
const totalActions = computed(() => tasks.value.reduce((sum, task) => sum + Number(task.max_actions || 0), 0))

function clonePlainValue<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function resetDraft() {
  objective.value = props.plan.objective
  tasks.value = clonePlainValue(props.plan.tasks)
  revisionNote.value = ''
  validationError.value = ''
}

watch(() => props.plan.version, () => {
  resetDraft()
  editing.value = false
}, { immediate: true })

function startEditing() {
  resetDraft()
  editing.value = true
}

function cancelEditing() {
  editing.value = false
  resetDraft()
}

function normalizeDependencies() {
  tasks.value = tasks.value.map((task, index) => ({
    ...task,
    dependencies: index === 0 ? [] : [tasks.value[index - 1]!.task_id],
    status: 'pending',
  }))
}

function moveTask(index: number, offset: number) {
  const target = index + offset
  if (target < 0 || target >= tasks.value.length) return
  const reordered = [...tasks.value]
  const [task] = reordered.splice(index, 1)
  if (!task) return
  reordered.splice(target, 0, task)
  tasks.value = reordered
  normalizeDependencies()
}

function removeTask(index: number) {
  if (tasks.value.length <= 1) return
  tasks.value.splice(index, 1)
  normalizeDependencies()
}

function addTask() {
  const existingNumbers = tasks.value.map(task => Number(task.task_id.match(/\d+$/)?.[0] ?? 0))
  const nextNumber = Math.max(0, ...existingNumbers) + 1
  const taskId = `task-${nextNumber}`
  const sourceIds = [...new Set(props.plan.tasks.flatMap(task => task.source_ids))]
  tasks.value.push({
    task_id: taskId,
    question: '',
    purpose: '',
    dependencies: tasks.value.length ? [tasks.value[tasks.value.length - 1]!.task_id] : [],
    allowed_tools: ['keyword_search', 'read_document_range'],
    source_ids: sourceIds,
    acceptance_criteria: [{
      criterion_id: `criterion-${nextNumber}`,
      description: 'evidence: 新任务取得可定位的原文依据',
      requires_evidence: true,
      dimension: 'evidence',
      target: '新任务取得可定位的原文依据',
      required: true,
    }],
    priority: 'normal',
    max_actions: 2,
    status: 'pending',
  })
}

function saveRevision() {
  validationError.value = ''
  if (!objective.value.trim()) validationError.value = '研究目标不能为空。'
  else if (tasks.value.some(task => !task.question.trim() || !task.purpose.trim())) validationError.value = '每个任务都需要问题和执行目的。'
  else if (totalActions.value > props.plan.budget.max_actions) validationError.value = `任务动作总数不能超过 ${props.plan.budget.max_actions}。`
  if (validationError.value) return
  emit('revise', {
    base_version: props.plan.version,
    objective: objective.value,
    tasks: clonePlainValue(tasks.value),
    report_spec: clonePlainValue(props.plan.report_spec),
    revision_note: revisionNote.value,
  })
}
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
      <p
        v-if="!editing"
        class="mt-4 text-sm leading-6 text-muted"
      >
        {{ plan.objective }}
      </p>
      <label
        v-else
        class="mt-4 block"
      >
        <span class="mb-2 block text-sm font-medium text-highlighted">研究目标</span>
        <textarea
          v-model="objective"
          rows="3"
          class="w-full rounded-lg border border-default bg-default px-3 py-2 text-sm leading-6 text-highlighted outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20"
        />
      </label>
    </div>

    <div class="space-y-3">
      <article
        v-for="(task, index) in (editing ? tasks : plan.tasks)"
        :key="task.task_id"
        class="rounded-xl border border-default bg-default p-4 shadow-sm"
      >
        <div class="flex items-start gap-3">
          <span class="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">{{ index + 1 }}</span>
          <div class="min-w-0 flex-1">
            <template v-if="editing">
              <div class="flex items-center justify-between gap-3">
                <span class="text-xs font-medium text-muted">{{ task.task_id }}</span>
                <div class="flex gap-1">
                  <UButton
                    icon="i-lucide-arrow-up"
                    color="neutral"
                    variant="ghost"
                    size="xs"
                    aria-label="上移任务"
                    :disabled="index === 0"
                    @click="moveTask(index, -1)"
                  />
                  <UButton
                    icon="i-lucide-arrow-down"
                    color="neutral"
                    variant="ghost"
                    size="xs"
                    aria-label="下移任务"
                    :disabled="index === tasks.length - 1"
                    @click="moveTask(index, 1)"
                  />
                  <UButton
                    icon="i-lucide-trash-2"
                    color="error"
                    variant="ghost"
                    size="xs"
                    aria-label="删除任务"
                    :disabled="tasks.length === 1"
                    @click="removeTask(index)"
                  />
                </div>
              </div>
              <label class="mt-3 block">
                <span class="mb-1.5 block text-xs font-medium text-muted">研究问题</span>
                <textarea
                  v-model="task.question"
                  rows="2"
                  class="w-full rounded-lg border border-default bg-default px-3 py-2 text-sm text-highlighted outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                />
              </label>
              <label class="mt-3 block">
                <span class="mb-1.5 block text-xs font-medium text-muted">执行目的</span>
                <input
                  v-model="task.purpose"
                  class="h-10 w-full rounded-lg border border-default bg-default px-3 text-sm text-highlighted outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                >
              </label>
              <label class="mt-3 block max-w-40">
                <span class="mb-1.5 block text-xs font-medium text-muted">最多动作数</span>
                <input
                  v-model.number="task.max_actions"
                  type="number"
                  min="1"
                  max="50"
                  class="h-10 w-full rounded-lg border border-default bg-default px-3 text-sm text-highlighted outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                >
              </label>
            </template>
            <template v-else>
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
            </template>
          </div>
        </div>
      </article>
    </div>

    <div
      v-if="editing"
      class="rounded-xl border border-dashed border-default p-4"
    >
      <UButton
        icon="i-lucide-plus"
        color="neutral"
        variant="soft"
        label="添加研究任务"
        @click="addTask"
      />
      <label class="mt-4 block">
        <span class="mb-1.5 block text-xs font-medium text-muted">修改说明（可选）</span>
        <input
          v-model="revisionNote"
          placeholder="例如：增加对生效日期的核验"
          class="h-10 w-full rounded-lg border border-default bg-default px-3 text-sm text-highlighted outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
        >
      </label>
      <p class="mt-3 text-xs text-muted">
        动作预算：{{ totalActions }} / {{ plan.budget.max_actions }}
      </p>
      <p
        v-if="validationError"
        role="alert"
        class="mt-3 text-sm text-error"
      >
        {{ validationError }}
      </p>
    </div>

    <div
      v-else
      class="grid gap-3 rounded-xl border border-default bg-elevated/30 p-4 text-sm sm:grid-cols-3"
    >
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
          动作预算
        </p><p class="mt-1 font-medium">
          {{ plan.tasks.reduce((sum, task) => sum + task.max_actions, 0) }} / {{ plan.budget.max_actions }}
        </p>
      </div>
    </div>

    <div class="flex flex-wrap items-center justify-between gap-3 border-t border-default pt-5">
      <p class="max-w-xl text-xs leading-5 text-muted">
        保存修改会生成新的计划版本；任何已有批准都不会自动沿用。
      </p>
      <div
        v-if="editing"
        class="flex gap-2"
      >
        <UButton
          color="neutral"
          variant="ghost"
          label="放弃修改"
          :disabled="revising"
          @click="cancelEditing"
        />
        <UButton
          icon="i-lucide-save"
          label="保存为新版本"
          :loading="revising"
          :disabled="revising"
          @click="saveRevision"
        />
      </div>
      <div
        v-else
        class="flex flex-wrap gap-2"
      >
        <UButton
          color="neutral"
          variant="ghost"
          label="取消任务"
          @click="emit('cancel')"
        />
        <UButton
          icon="i-lucide-pencil"
          color="neutral"
          variant="soft"
          label="修改计划"
          @click="startEditing"
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
