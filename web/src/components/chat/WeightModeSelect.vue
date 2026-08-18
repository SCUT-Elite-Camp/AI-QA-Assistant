<script setup lang="ts">
import { ref, watch, computed } from 'vue'

const props = withDefaults(defineProps<{
  modelValue?: 'thinking' | 'auto' | 'fast' | string
}>(), {
  modelValue: 'thinking'
})

const emit = defineEmits<{
  (e: 'update:modelValue', val: 'thinking' | 'auto' | 'fast'): void
  (e: 'change', val: 'thinking' | 'auto' | 'fast'): void
}>()

const mode = ref<'thinking' | 'auto' | 'fast'>((props.modelValue as any) || 'thinking')

watch(() => props.modelValue, (val) => {
  if (val) {
    if (val === 'deeper') mode.value = 'thinking'
    else if (val === 'wider') mode.value = 'fast'
    else mode.value = val as 'thinking' | 'auto' | 'fast'
  }
})

function selectMode(m: 'thinking' | 'auto' | 'fast') {
  mode.value = m
  emit('update:modelValue', m)
  emit('change', m)
}

const displayLabel = computed(() => {
  if (mode.value === 'thinking' || mode.value === ('deeper' as any)) return 'Thinking'
  if (mode.value === 'fast' || mode.value === ('wider' as any)) return 'Fast'
  return 'Auto'
})

const menuItems = computed(() => [[
  {
    label: 'Auto',
    icon: 'i-lucide-sparkles',
    onSelect: () => selectMode('auto')
  },
  {
    label: 'Fast',
    icon: 'i-lucide-zap',
    onSelect: () => selectMode('fast')
  },
  {
    label: 'Thinking',
    icon: 'i-lucide-brain',
    onSelect: () => selectMode('thinking')
  }
]])
</script>

<template>
  <UDropdownMenu
    :items="menuItems"
    :content="{ align: 'end' }"
  >
    <UButton
      color="neutral"
      variant="ghost"
      size="sm"
      class="text-sm font-semibold text-zinc-200 hover:text-white flex items-center gap-1 cursor-pointer px-2"
    >
      <span>{{ displayLabel }}</span>
      <UIcon name="i-lucide-chevron-down" class="w-4 h-4 text-zinc-400 ms-0.5" />
    </UButton>
  </UDropdownMenu>
</template>
