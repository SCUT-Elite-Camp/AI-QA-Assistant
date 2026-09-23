<script setup lang="ts">
import { ref } from 'vue'

defineProps<{
  title: string
  description: string
  color?: 'error' | 'warning' | 'info' | 'success'
}>()

const emit = defineEmits<{ close: [boolean] }>()

const open = ref(true)

function onOpenChange(v: boolean) {
  if (!v) emit('close', false)
}
</script>

<template>
  <UModal
    v-model:open="open"
    @update:open="onOpenChange"
    :title="title"
    :description="description"
    :ui="{
      footer: 'flex-row-reverse justify-start'
    }"
    :close="false"
    :dismissible="false"
  >
    <template #footer>
      <UButton
        :color="color"
        label="Delete"
        @click="emit('close', true)"
      />
      <UButton
        color="neutral"
        variant="ghost"
        label="Cancel"
        @click="emit('close', false)"
      />
    </template>
  </UModal>
</template>
