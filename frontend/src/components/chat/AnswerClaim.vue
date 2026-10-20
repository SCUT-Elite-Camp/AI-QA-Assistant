<script setup lang="ts">
import { inject } from 'vue'

defineProps<{ claimId: string }>()
const open = inject<(id: string) => void>('openAnswerClaim', () => {})
</script>

<template>
  <span
    role="button"
    tabindex="0"
    class="answer-claim cursor-pointer rounded-sm font-normal underline decoration-dotted decoration-neutral-400/60 underline-offset-4 hover:decoration-primary focus-visible:outline-2 focus-visible:outline-primary"
    aria-label="Show supporting quotes"
    aria-haspopup="dialog"
    @click.stop.prevent="open(claimId)"
    @keydown.enter.stop.prevent="open(claimId)"
    @keydown.space.stop.prevent="open(claimId)"
  ><slot /></span>
</template>
