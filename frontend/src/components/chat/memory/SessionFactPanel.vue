<script setup lang="ts">
import { computed } from 'vue'
import type { FactView } from '../../../types/memory'

const props = defineProps<{
  facts: FactView[]
  isPending: (factId: string) => boolean
}>()

const emit = defineEmits<{
  revoke: [factId: string]
}>()

const categoryLabel: Record<FactView['category'], string> = {
  GOAL: '目标',
  PREFERENCE: '偏好',
  PLAN_CONSTRAINT: '计划约束'
}

const visibleFacts = computed(() => props.facts.filter(fact => (
  fact.status === 'CONFIRMED'
  && (!fact.expiresAt || new Date(fact.expiresAt).getTime() > Date.now())
)))

function formatExpiry(expiresAt: string | null): string {
  if (!expiresAt) return '无到期日'
  return new Date(expiresAt).toLocaleDateString()
}
</script>

<template>
  <UCard
    v-if="visibleFacts.length"
    class="border border-default"
  >
    <template #header>
      <div class="flex items-center gap-2">
        <UIcon
          name="i-lucide-brain"
          class="size-4 text-primary"
        />
        <span class="font-medium">本会话记忆</span>
      </div>
    </template>

    <ul class="space-y-3">
      <li
        v-for="fact in visibleFacts"
        :key="fact.id"
        class="flex items-start gap-3"
      >
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <UBadge
              color="neutral"
              variant="subtle"
              size="xs"
            >
              {{ categoryLabel[fact.category] }}
            </UBadge>
            <span class="text-xs text-muted">到期：{{ formatExpiry(fact.expiresAt) }}</span>
          </div>
          <p class="mt-1 text-sm whitespace-pre-wrap break-words">
            {{ fact.value }}
          </p>
        </div>
        <UButton
          size="xs"
          color="neutral"
          variant="ghost"
          :loading="isPending(fact.id)"
          :disabled="isPending(fact.id)"
          @click="emit('revoke', fact.id)"
        >
          撤销
        </UButton>
      </li>
    </ul>
  </UCard>
</template>
