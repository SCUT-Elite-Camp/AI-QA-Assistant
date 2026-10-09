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
  GOAL: 'Goal',
  PREFERENCE: 'Preference',
  PLAN_CONSTRAINT: 'Constraint'
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
          <span class="text-sm font-medium">Suggested Session Memory</span>
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
          Dismiss
        </UButton>
        <UButton
          size="xs"
          color="primary"
          :loading="props.pending"
          :disabled="props.pending"
          @click="emit('confirm', props.fact.id)"
        >
          Confirm
        </UButton>
      </div>
    </div>
  </UCard>
</template>
