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
  GOAL: 'Goal',
  PREFERENCE: 'Preference',
  PLAN_CONSTRAINT: 'Constraint'
}

const visibleFacts = computed(() => props.facts.filter(fact => (
  fact.status === 'CONFIRMED'
  && (!fact.expiresAt || new Date(fact.expiresAt).getTime() > Date.now())
)))

function formatExpiry(expiresAt: string | null): string {
  if (!expiresAt) return 'No expiry'
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
        <span class="font-medium">Session Memory</span>
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
            <span class="text-xs text-muted">Expires: {{ formatExpiry(fact.expiresAt) }}</span>
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
          Revoke
        </UButton>
      </li>
    </ul>
  </UCard>
</template>
