<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  index: string | number
  chunkText?: string
  title?: string
}>()

const visible = ref(false)
const tooltipRef = ref<HTMLElement | null>(null)
const anchorRef = ref<HTMLElement | null>(null)
const tooltipStyle = ref<{ top: string; left: string; transform: string }>({
  top: '0px',
  left: '0px',
  transform: 'translateX(-50%)',
})

function show() {
  visible.value = true
  // Position after next tick so the tooltip is mounted
  setTimeout(() => {
    if (!anchorRef.value || !tooltipRef.value) return
    const rect = anchorRef.value.getBoundingClientRect()
    const tip = tooltipRef.value.getBoundingClientRect()
    const viewW = window.innerWidth

    // Default: centered above the anchor
    let left = rect.left + rect.width / 2
    let transform = 'translateX(-50%)'

    // Clamp so tooltip doesn't overflow viewport
    const halfTip = tip.width / 2
    if (left - halfTip < 8) {
      left = halfTip + 8
      transform = 'translateX(-50%)'
    } else if (left + halfTip > viewW - 8) {
      left = viewW - halfTip - 8
      transform = 'translateX(-50%)'
    }

    tooltipStyle.value = {
      top: `${rect.top + window.scrollY - tip.height - 8}px`,
      left: `${left + window.scrollX}px`,
      transform,
    }
  }, 0)
}

function hide() {
  visible.value = false
}
</script>

<template>
  <!-- Inline citation marker: superscript number -->
  <sup
    ref="anchorRef"
    class="cite-mark"
    :aria-label="`引用来源 ${props.index}`"
    @mouseenter="show"
    @mouseleave="hide"
    @focusin="show"
    @focusout="hide"
  >{{ props.index }}</sup>

  <!-- Teleported tooltip -->
  <Teleport to="body">
    <Transition name="cite-tooltip">
      <div
        v-if="visible && props.chunkText"
        ref="tooltipRef"
        class="cite-tooltip"
        :style="tooltipStyle"
        role="tooltip"
        @mouseenter="show"
        @mouseleave="hide"
      >
        <p v-if="props.title" class="cite-tooltip__title">{{ props.title }}</p>
        <p class="cite-tooltip__text">{{ props.chunkText }}</p>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.cite-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.15em;
  height: 1.15em;
  min-width: 1.15em;
  font-size: 0.7em;
  font-weight: 600;
  font-style: normal;
  line-height: 1;
  vertical-align: super;
  color: var(--ui-color-primary-500, #6366f1);
  background: color-mix(in srgb, var(--ui-color-primary-500, #6366f1) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--ui-color-primary-500, #6366f1) 30%, transparent);
  border-radius: 50%;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s, color 0.15s, transform 0.1s;
  position: relative;
  top: -0.1em;
  margin: 0 0.15em;
}

.cite-mark:hover {
  background: color-mix(in srgb, var(--ui-color-primary-500, #6366f1) 22%, transparent);
  transform: scale(1.12);
}
</style>

<style>
/* Non-scoped so the teleported tooltip inherits theme vars */
.cite-tooltip {
  position: absolute;
  z-index: 9999;
  max-width: 340px;
  min-width: 180px;
  padding: 10px 13px;
  background: var(--ui-bg-elevated, #1e2030);
  border: 1px solid var(--ui-border, rgba(255,255,255,0.1));
  border-radius: 10px;
  box-shadow: 0 8px 30px rgba(0,0,0,0.35);
  pointer-events: auto;
}

.cite-tooltip__title {
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--ui-color-primary-400, #818cf8);
  margin: 0 0 5px 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cite-tooltip__text {
  font-size: 0.78rem;
  line-height: 1.55;
  color: var(--ui-text-muted, #9ca3af);
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 6;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* Transition */
.cite-tooltip-enter-active,
.cite-tooltip-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.cite-tooltip-enter-from,
.cite-tooltip-leave-to {
  opacity: 0;
  transform: translateX(var(--tx, -50%)) translateY(4px) !important;
}
</style>
