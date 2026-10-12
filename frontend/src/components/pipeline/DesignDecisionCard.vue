<script setup lang="ts">
import type { DesignDecisionItem } from './pipelineNodes'

defineProps<{
  decision: DesignDecisionItem
  active: boolean
}>()

const emit = defineEmits<{
  (e: 'select', id: string): void
}>()
</script>

<template>
  <div
    class="decision-card"
    :class="{ active }"
    @click="emit('select', decision.id)"
  >
    <div class="decision-card-top">
      <span class="decision-num">{{ decision.step }}</span>
      <div
        class="decision-icon-wrap"
        :style="{ background: decision.colorBg, color: decision.color }"
      >
        <svg
          v-if="decision.icon === 'document'"
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
        </svg>

        <svg
          v-else-if="decision.icon === 'layers'"
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <polygon points="12 2 2 7 12 12 22 7 12 2" />
          <polyline points="2 17 12 22 22 17" />
          <polyline points="2 12 12 17 22 12" />
        </svg>

        <svg
          v-else-if="decision.icon === 'refresh'"
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <polyline points="23 4 23 10 17 10" />
          <polyline points="1 20 1 14 7 14" />
          <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
        </svg>
      </div>

      <div class="decision-body">
        <h3 class="decision-heading">{{ decision.title }}</h3>
        <p class="decision-desc">{{ decision.desc }}</p>
      </div>
    </div>

    <div class="decision-arrow-wrap">
      <div class="decision-arrow">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M5 12h14" />
          <path d="m12 5 7 7-7 7" />
        </svg>
      </div>
    </div>
  </div>
</template>

<style scoped>
.decision-card {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  padding: 24px 26px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-height: 144px;
  color: inherit;
  cursor: pointer;
  transition: all 0.22s cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.03);
  position: relative;
}

.decision-card:hover {
  border-color: #cbd5e1;
  transform: translateY(-2px);
  box-shadow: 0 4px 16px -2px rgba(15, 23, 42, 0.06);
}

.decision-card.active {
  border-color: #2563eb;
  box-shadow: 0 6px 20px rgba(37, 99, 235, 0.12);
}

.decision-card-top {
  display: flex;
  align-items: flex-start;
  gap: 16px;
}

.decision-num {
  font-family: var(--font-mono, monospace);
  font-size: 20px;
  font-weight: 700;
  color: #94a3b8;
  line-height: 1;
  margin-top: 2px;
  transition: color 0.15s ease;
}

.decision-card:hover .decision-num,
.decision-card.active .decision-num {
  color: #2563eb;
}

.decision-icon-wrap {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.decision-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1;
}

.decision-heading {
  font-size: 16px;
  font-weight: 700;
  color: #111827;
  letter-spacing: -0.015em;
}

.decision-desc {
  font-size: 13px;
  line-height: 1.55;
  color: #64748b;
}

.decision-arrow-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.decision-arrow {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: #f8fafc;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #64748b;
  transition: all 0.15s ease;
}

.decision-card:hover .decision-arrow {
  background: #2563eb;
  color: #ffffff;
  transform: translateX(3px);
}
</style>
