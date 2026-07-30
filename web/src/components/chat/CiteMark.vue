<script setup lang="ts">
import { inject, computed, ref, nextTick } from 'vue'
import type { ComputedRef } from 'vue'
import type { ChunkCitation } from './tool/Sources.vue'

const props = defineProps<{
  index: string | number
}>()

const citationMap = inject<ComputedRef<Map<number, ChunkCitation>>>('ragCitationMap')

const citation = computed(() =>
  citationMap?.value?.get(Number(props.index)) ?? null
)

const visible = ref(false)
const anchorRef = ref<HTMLElement | null>(null)
const tooltipRef = ref<HTMLElement | null>(null)
const tooltipStyle = ref({ top: '0px', left: '0px' })

let closeTimeout: number | null = null

function calculatePosition() {
  if (!anchorRef.value || !tooltipRef.value) return
  const rect = anchorRef.value.getBoundingClientRect()
  const tipRect = tooltipRef.value.getBoundingClientRect()

  const tipWidth = tipRect.width || 288
  const tipHeight = tipRect.height || 200

  // Center horizontally under the badge
  let left = rect.left + rect.width / 2 - tipWidth / 2
  // Clamp to screen bounds
  left = Math.max(8, Math.min(left, window.innerWidth - tipWidth - 8))

  // Try placing it below the badge by default
  let top = rect.bottom + 6
  // If it overflows the bottom of the viewport, place it above the badge
  if (top + tipHeight > window.innerHeight - 8) {
    top = rect.top - tipHeight - 6
  }

  tooltipStyle.value = {
    top: `${top + window.scrollY}px`,
    left: `${left + window.scrollX}px`,
  }
}

async function show() {
  if (closeTimeout) {
    clearTimeout(closeTimeout)
    closeTimeout = null
  }
  visible.value = true
  await nextTick()
  calculatePosition()
}

function hide() {
  if (closeTimeout) clearTimeout(closeTimeout)
  closeTimeout = window.setTimeout(() => {
    visible.value = false
  }, 150)
}

function keepOpen() {
  if (closeTimeout) {
    clearTimeout(closeTimeout)
    closeTimeout = null
  }
}
</script>

<template>
  <span ref="anchorRef" class="inline-block align-middle select-none">
    <!-- Circle badge matching UButton neutral outline rounded-full -->
    <UButton
      size="xs"
      color="neutral"
      variant="outline"
      class="cite-badge-btn"
      @mouseenter="show"
      @mouseleave="hide"
      @focusin="show"
      @focusout="hide"
    >
      {{ index }}
    </UButton>
  </span>

  <Teleport to="body">
    <Transition name="fade-slide">
      <div
        v-if="visible && citation"
        ref="tooltipRef"
        class="absolute z-50 w-80 bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 rounded-lg shadow-lg overflow-hidden"
        :style="tooltipStyle"
        @mouseenter="keepOpen"
        @mouseleave="hide"
      >
        <!-- Header -->
        <div class="flex items-center gap-2 px-3 py-2 border-b border-neutral-100 dark:border-neutral-800 bg-neutral-50/50 dark:bg-neutral-900/50">
          <span class="inline-flex items-center justify-center w-4 h-4 text-[9px] font-bold rounded-full border border-neutral-200 dark:border-neutral-700 text-neutral-500 dark:text-neutral-400 bg-neutral-100 dark:bg-neutral-800">
            {{ index }}
          </span>
          <span class="text-xs font-semibold text-neutral-700 dark:text-neutral-300 truncate flex-1">
            {{ citation.title }}
          </span>
        </div>
        <!-- Scrollable content -->
        <div class="p-3 text-xs text-neutral-600 dark:text-neutral-300 leading-relaxed max-h-72 overflow-y-auto whitespace-pre-wrap select-text cite-scroll-container">
          {{ citation.chunk_text || '（暂无摘要）' }}
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.cite-badge-btn {
  width: 18px !important;
  height: 18px !important;
  min-width: 18px !important;
  min-height: 18px !important;
  padding: 0 !important;
  font-size: 9px !important;
  font-weight: 700 !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  vertical-align: middle;
  margin: 0 2px;
  border-radius: 9999px !important;
}

/* Custom thin scrollbar for tooltip content */
.cite-scroll-container {
  scrollbar-width: thin;
  scrollbar-color: rgba(0, 0, 0, 0.15) transparent;
}
html.dark .cite-scroll-container {
  scrollbar-color: rgba(255, 255, 255, 0.15) transparent;
}
.cite-scroll-container::-webkit-scrollbar {
  width: 4px;
}
.cite-scroll-container::-webkit-scrollbar-track {
  background: transparent;
}
.cite-scroll-container::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.15);
  border-radius: 2px;
}
html.dark .cite-scroll-container::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.15);
}

/* Vue Transition */
.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: opacity 0.12s ease, transform 0.12s ease;
}
.fade-slide-enter-from,
.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(3px);
}
</style>
