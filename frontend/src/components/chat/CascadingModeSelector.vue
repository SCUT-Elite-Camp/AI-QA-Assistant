<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  modelValue?: 'auto' | 'fast' | 'thinking'
  disabled?: boolean
}>(), {
  modelValue: 'fast',
  disabled: false
})

const emit = defineEmits<{
  (e: 'update:modelValue', val: 'auto' | 'fast' | 'thinking'): void
  (e: 'change', val: 'auto' | 'fast' | 'thinking'): void
}>()

interface ModeConfig {
  id: 'auto' | 'fast' | 'thinking'
  label: string
  dotClass: string
}

const modes: ModeConfig[] = [
  {
    id: 'auto',
    label: 'Auto',
    dotClass: 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]'
  },
  {
    id: 'fast',
    label: 'Fast',
    dotClass: 'bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.8)]'
  },
  {
    id: 'thinking',
    label: 'Thinking',
    dotClass: 'bg-purple-400 shadow-[0_0_8px_rgba(192,132,252,0.8)]'
  }
]

const defaultMode: ModeConfig = {
  id: 'fast',
  label: 'Fast',
  dotClass: 'bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.8)]'
}

const currentMode = computed(() => {
  return modes.find(m => m.id === props.modelValue) || defaultMode
})

function cycleNext() {
  const currentIndex = modes.findIndex(m => m.id === props.modelValue)
  const nextIndex = (currentIndex + 1) % modes.length
  const nextMode = modes[nextIndex]?.id ?? defaultMode.id
  emit('update:modelValue', nextMode)
  emit('change', nextMode)
}
</script>

<template>
  <button
    type="button"
    :disabled="props.disabled"
    :aria-label="`Mode: ${currentMode.label}`"
    :title="`Current mode: ${currentMode.label} (Click to toggle)`"
    :class="[
      'h-9 px-3.5 sm:px-4 rounded-full text-sm font-medium tracking-normal transition-all duration-200 cursor-pointer flex items-center justify-center border shadow-2xs select-none overflow-hidden relative active:scale-95 shrink-0',
      'bg-zinc-100 hover:bg-zinc-200/80 dark:bg-zinc-800/90 dark:hover:bg-zinc-700/80 border-zinc-200/90 dark:border-zinc-700/70 text-zinc-800 dark:text-zinc-100 hover:text-zinc-950 dark:hover:text-white',
      props.disabled ? 'opacity-50 cursor-not-allowed' : ''
    ]"
    @click="cycleNext"
  >
    <Transition name="roller-slide">
      <div
        :key="currentMode.id"
        class="flex items-center gap-2 whitespace-nowrap select-none font-sans"
      >
        <span class="w-2 h-2 rounded-full shrink-0" :class="currentMode.dotClass" />
        <span class="text-sm font-medium leading-none">{{ currentMode.label }}</span>
      </div>
    </Transition>
  </button>
</template>

<style scoped>
.roller-slide-enter-active,
.roller-slide-leave-active {
  transition: transform 0.22s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.18s ease;
}

.roller-slide-enter-from {
  opacity: 0;
  transform: translateY(-100%);
}

.roller-slide-leave-to {
  opacity: 0;
  transform: translateY(100%);
}

.roller-slide-leave-active {
  position: absolute;
}
</style>
