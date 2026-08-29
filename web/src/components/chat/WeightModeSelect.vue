<script setup lang="ts">
import { ref, watch, computed } from 'vue'

const props = defineProps<{
  modelValue?: 'deeper' | 'auto' | 'wider'
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', val: 'deeper' | 'auto' | 'wider'): void
  (e: 'change', val: 'deeper' | 'auto' | 'wider'): void
}>()

const mode = ref<'deeper' | 'auto' | 'wider'>(props.modelValue || 'auto')

watch(() => props.modelValue, (val) => {
  if (val) mode.value = val
})

function selectMode(m: 'deeper' | 'auto' | 'wider') {
  mode.value = m
  emit('update:modelValue', m)
  emit('change', m)
}

const displayLabel = computed(() => {
  if (mode.value === 'deeper') return 'Deeper'
  if (mode.value === 'wider') return 'Wider'
  return 'Auto'
})
</script>

<template>
  <UDropdownMenu
    :items="[[
      { label: 'Auto', onSelect: () => selectMode('auto') },
      { label: 'Deeper', onSelect: () => selectMode('deeper') },
      { label: 'Wider', onSelect: () => selectMode('wider') }
    ]]"
    :content="{ align: 'start' }"
  >
    <UButton
      color="neutral"
      variant="ghost"
      size="sm"
      class="text-sm font-semibold text-zinc-200 hover:text-white flex items-center gap-1 cursor-pointer px-2"
    >
      <span>{{ displayLabel }}</span>
      <UIcon name="i-heroicons-chevron-down" class="w-4 h-4 text-zinc-400 ms-0.5" />
    </UButton>
  </UDropdownMenu>
</template>
