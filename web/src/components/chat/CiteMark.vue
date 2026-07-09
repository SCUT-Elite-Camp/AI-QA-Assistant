<script setup lang="ts">
import { inject, computed } from 'vue'
import type { ComputedRef } from 'vue'
import type { ChunkCitation } from './tool/Sources.vue'

const props = defineProps<{
  index: string | number
}>()

// Receive citation map from the parent MessageContent via provide/inject
const citationMap = inject<ComputedRef<Map<number, ChunkCitation>>>('ragCitationMap')

const citation = computed(() => {
  if (!citationMap?.value) return null
  return citationMap.value.get(Number(props.index)) ?? null
})
</script>

<template>
  <span class="cite-wrap">
    <sup class="cite-badge" :aria-label="`引用来源 ${index}`">{{ index }}</sup>

    <!-- CSS-driven tooltip (no Teleport needed for simple use) -->
    <span
      v-if="citation"
      class="cite-tip"
      role="tooltip"
    >
      <span v-if="citation.title" class="cite-tip__title">{{ citation.title }}</span>
      <span v-if="citation.chunk_text" class="cite-tip__body">{{ citation.chunk_text }}</span>
    </span>
  </span>
</template>

<style scoped>
/* ── wrapper ── */
.cite-wrap {
  position: relative;
  display: inline-block;
}

/* ── badge: small filled circle ── */
.cite-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.25em;
  height: 1.25em;
  font-size: 0.62em;
  font-weight: 700;
  font-style: normal;
  line-height: 1;
  letter-spacing: -0.01em;
  vertical-align: super;
  position: relative;
  top: -0.05em;
  margin: 0 0.1em;
  color: #fff;
  background: #6366f1;
  border-radius: 50%;
  cursor: default;
  user-select: none;
  transition: background 0.15s ease, transform 0.12s ease, box-shadow 0.15s ease;
  box-shadow: 0 1px 4px rgba(99, 102, 241, 0.35);
}

.cite-wrap:hover .cite-badge {
  background: #4f46e5;
  transform: scale(1.18);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.5);
}

/* ── tooltip ── */
.cite-tip {
  display: none;
  position: absolute;
  bottom: calc(100% + 8px);
  left: 50%;
  transform: translateX(-50%);
  z-index: 999;
  width: 260px;
  padding: 9px 12px;
  background: #1e2030;
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 9px;
  box-shadow: 0 6px 24px rgba(0,0,0,0.40);
  pointer-events: none;
  white-space: normal;
  text-align: left;
}

/* tiny arrow */
.cite-tip::after {
  content: '';
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 5px solid transparent;
  border-top-color: #1e2030;
}

.cite-wrap:hover .cite-tip {
  display: flex;
  flex-direction: column;
  gap: 4px;
  animation: tip-in 0.14s ease;
}

.cite-tip__title {
  font-size: 0.68rem;
  font-weight: 600;
  color: #a5b4fc;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cite-tip__body {
  font-size: 0.74rem;
  line-height: 1.5;
  color: #9ca3af;
  display: -webkit-box;
  -webkit-line-clamp: 5;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

@keyframes tip-in {
  from { opacity: 0; transform: translateX(-50%) translateY(4px); }
  to   { opacity: 1; transform: translateX(-50%) translateY(0); }
}
</style>
