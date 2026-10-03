<script setup lang="ts">
import type { FactView } from '../../../types/memory'

const props = defineProps<{
  fact: FactView
  pending: boolean
}>()

const emit = defineEmits<{
  confirm: [factId: string]
  revoke: [factId: string]
}>()

const categoryLabel: Record<FactView['category'], string> = {
  GOAL: '目标',
  PREFERENCE: '偏好',
  PLAN_CONSTRAINT: '计划约束'
}
</script>

<template>
  <UCard class="border border-primary/25 bg-primary/5">
    <div class="flex flex-col gap-3">
      <div class="flex items-center justify-between gap-3">
        <div class="flex items-center gap-2">
          <UIcon
            name="i-lucide-brain"
            class="size-4 text-primary"
          />
          <span class="text-sm font-medium">建议保存为会话记忆</span>
        </div>
        <UBadge
          color="primary"
          variant="subtle"
          size="xs"
        >
          {{ categoryLabel[props.fact.category] }}
        </UBadge>
      </div>
      <p class="text-sm text-muted whitespace-pre-wrap break-words">
        {{ props.fact.value }}
      </p>
      <div class="flex justify-end gap-2">
        <UButton
          size="xs"
          color="neutral"
          variant="ghost"
          :loading="props.pending"
          :disabled="props.pending"
          @click="emit('revoke', props.fact.id)"
        >
          拒绝
        </UButton>
        <UButton
          size="xs"
          color="primary"
          :loading="props.pending"
          :disabled="props.pending"
          @click="emit('confirm', props.fact.id)"
        >
          确认
        </UButton>
      </div>
    </div>
  </UCard>
</template>
