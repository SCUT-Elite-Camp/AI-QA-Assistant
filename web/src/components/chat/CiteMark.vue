<script setup lang="ts">
import { inject, computed, ref } from 'vue'
import type { ComputedRef } from 'vue'
import type { ChunkCitation } from './tool/Sources.vue'

const props = defineProps<{
  index: string | number
}>()

const citationMap = inject<ComputedRef<Map<number, ChunkCitation>>>('ragCitationMap')

const citation = computed(() =>
  citationMap?.value?.get(Number(props.index)) ?? null
)

// ── tooltip positioning (follows cursor, fixed to viewport) ──
const visible = ref(false)
const tipStyle = ref({ top: '0px', left: '0px' })

const TIP_W = 300
const TIP_H_EST = 200 // conservative estimate
const OFFSET = 14

function place(e: MouseEvent) {
  let left = e.clientX + OFFSET
  let top  = e.clientY + OFFSET
  if (left + TIP_W  > window.innerWidth  - 8) left = e.clientX - TIP_W - OFFSET
  if (top  + TIP_H_EST > window.innerHeight - 8) top = e.clientY - TIP_H_EST - OFFSET
  tipStyle.value = { top: `${top}px`, left: `${left}px` }
}

function onEnter(e: MouseEvent) { visible.value = true;  place(e) }
function onMove (e: MouseEvent) { place(e) }
function onLeave()              { visible.value = false }
</script>

<template>
  <!-- Inline circle badge — same neutral/outline token as SourceLink -->
  <span
    class="cite-badge"
    :aria-label="`引用来源 ${index}`"
    @mouseenter="onEnter"
    @mousemove="onMove"
    @mouseleave="onLeave"
  >{{ index }}</span>

  <!-- Tooltip: fixed to viewport, fully scrollable, never clipped -->
  <Teleport to="body">
    <Transition name="cite-fade">
      <div
        v-if="visible && citation"
        class="cite-tip"
        :style="tipStyle"
        @mouseenter="visible = true"
        @mouseleave="onLeave"
      >
        <!-- header -->
        <div class="cite-tip__header">
          <span class="cite-tip__index">{{ index }}</span>
          <span class="cite-tip__title">{{ citation.title }}</span>
        </div>
        <!-- scrollable body -->
        <div class="cite-tip__body">
          {{ citation.chunk_text || '（暂无摘要）' }}
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
/* ── Circle badge: matches UButton neutral outline xs rounded-full ── */
.cite-badge {
  /* geometry */
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.35em;
  height: 1.35em;
  border-radius: 9999px;

  /* typography */
  font-size: 0.68em;
  font-weight: 600;
  font-style: normal;
  line-height: 1;
  letter-spacing: 0;

  /* positioning inside prose */
  vertical-align: middle;
  position: relative;
  top: -0.5px;
  margin: 0 0.15em;

  /* neutral / outline token — mirrors UButton neutral outline */
  color:            var(--ui-text-muted);
  background:       transparent;
  border:           1px solid var(--ui-border-accented, color-mix(in srgb, currentColor 20%, transparent));
  box-shadow:       none;

  cursor: default;
  user-select: none;
  transition: background 0.12s, color 0.12s, border-color 0.12s;
}

.cite-badge:hover {
  background:    var(--ui-bg-elevated, rgba(255,255,255,0.06));
  color:         var(--ui-text);
  border-color:  var(--ui-border, currentColor);
}
</style>

<!-- tooltip lives in <body> so it can never be clipped -->
<style>
.cite-tip {
  position: fixed;
  z-index: 9999;
  width: 300px;

  /* card style — same elevated surface as the rest of the UI */
  background:   var(--ui-bg-elevated, #1e2030);
  border:       1px solid var(--ui-border, rgba(255,255,255,0.10));
  border-radius: 10px;
  box-shadow:   0 8px 32px rgba(0,0,0,0.30);
  overflow: hidden;

  /* prevent mouse gaps from closing tooltip */
  pointer-events: auto;
}

/* ── header row ── */
.cite-tip__header {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 9px 12px 8px;
  border-bottom: 1px solid var(--ui-border, rgba(255,255,255,0.08));
}

.cite-tip__index {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.5em;
  height: 1.5em;
  font-size: 0.68rem;
  font-weight: 700;
  border-radius: 9999px;
  color:         var(--ui-text-muted);
  border:        1px solid var(--ui-border-accented, rgba(255,255,255,0.18));
  background:    transparent;
}

.cite-tip__title {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--ui-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  min-width: 0;
}

/* ── scrollable body ── */
.cite-tip__body {
  padding: 9px 12px 11px;
  font-size: 0.76rem;
  line-height: 1.6;
  color: var(--ui-text-muted);
  max-height: 180px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;

  /* thin scrollbar */
  scrollbar-width: thin;
  scrollbar-color: rgba(255,255,255,0.15) transparent;
}
.cite-tip__body::-webkit-scrollbar       { width: 4px; }
.cite-tip__body::-webkit-scrollbar-track { background: transparent; }
.cite-tip__body::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.15); border-radius: 2px; }

/* ── transition ── */
.cite-fade-enter-active,
.cite-fade-leave-active {
  transition: opacity 0.12s ease, transform 0.12s ease;
}
.cite-fade-enter-from,
.cite-fade-leave-to {
  opacity: 0;
  transform: translateY(3px);
}
</style>
