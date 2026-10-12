<script setup lang="ts">
import type { WikiPanelPayload } from './pipelineNodes'

defineProps<{
  data: WikiPanelPayload
  active: boolean
}>()

const emit = defineEmits<{
  (e: 'select'): void
}>()
</script>

<template>
  <div
    class="wiki-panel-card"
    :class="{ active }"
    @click="emit('select')"
  >
    <!-- Header -->
    <div class="wiki-header-row">
      <div class="wiki-badge-group">
        <div class="wiki-icon-badge">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
          </svg>
        </div>
        <span class="wiki-brand-title">{{ data.title }}</span>
      </div>
      <div class="wiki-arrow-btn">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M5 12h14" />
          <path d="m12 5 7 7-7 7" />
        </svg>
      </div>
    </div>

    <!-- Intro -->
    <div class="wiki-intro-group">
      <h2 class="wiki-headline">{{ data.headline }}</h2>
      <p class="wiki-desc">{{ data.description }}</p>
    </div>

    <!-- Three Features -->
    <div class="wiki-features-list">
      <div
        v-for="feature in data.features"
        :key="feature.id"
        class="wiki-feature-item"
      >
        <div class="wiki-feature-icon" :style="{ color: feature.color }">
          <svg
            v-if="feature.icon === 'compass'"
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <circle cx="12" cy="12" r="10" />
            <polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76" />
          </svg>

          <svg
            v-else-if="feature.icon === 'ban'"
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <circle cx="12" cy="12" r="10" />
            <line x1="8" y1="12" x2="16" y2="12" />
          </svg>

          <svg
            v-else-if="feature.icon === 'shield-lock'"
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
        </div>
        <div class="wiki-feature-text">
          <span class="wiki-feature-title">{{ feature.title }}</span>
          <span class="wiki-feature-desc">{{ feature.desc }}</span>
        </div>
      </div>
    </div>

    <!-- 概念微示意图 -->
    <div class="wiki-micro-art">
      <div style="display:flex; flex-direction:column; gap:6px; width:72px;">
        <div style="height:12px; background:#e2e8f0; border-radius:3px; width:100%;"></div>
        <div style="height:6px; background:#cbd5e1; border-radius:2px; width:80%;"></div>
        <div style="height:6px; background:#cbd5e1; border-radius:2px; width:65%;"></div>
        <div style="height:6px; background:#cbd5e1; border-radius:2px; width:90%;"></div>
      </div>

      <svg width="40" height="20" viewBox="0 0 40 20" fill="none">
        <path d="M2 10H34M34 10L26 4M34 10L26 16" stroke="#94a3b8" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="3 3"/>
      </svg>

      <div style="display:flex; flex-direction:column; gap:8px;">
        <div style="display:flex; align-items:center; gap:8px;">
          <div style="width:8px; height:8px; border-radius:50%; background:#2563eb;"></div>
          <div style="width:48px; height:6px; background:#93c5fd; border-radius:2px;"></div>
        </div>
        <div style="display:flex; align-items:center; gap:8px; padding-left:12px;">
          <div style="width:7px; height:7px; border-radius:50%; background:#8b5cf6;"></div>
          <div style="width:40px; height:5px; background:#c4b5fd; border-radius:2px;"></div>
        </div>
        <div style="display:flex; align-items:center; gap:8px; padding-left:12px;">
          <div style="width:7px; height:7px; border-radius:50%; background:#10b981;"></div>
          <div style="width:36px; height:5px; background:#a7f3d0; border-radius:2px;"></div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wiki-panel-card {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 16px;
  padding: 24px 26px;
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.03);
  display: flex;
  flex-direction: column;
  gap: 18px;
  transition: all 0.24s cubic-bezier(0.16, 1, 0.3, 1);
  cursor: pointer;
}

.wiki-panel-card:hover {
  border-color: #cbd5e1;
  box-shadow: 0 4px 16px -2px rgba(15, 23, 42, 0.06);
  transform: translateY(-2px);
}

.wiki-panel-card.active {
  border-color: #2563eb;
  box-shadow: 0 8px 24px rgba(37, 99, 235, 0.1);
}

.wiki-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.wiki-badge-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.wiki-icon-badge {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: #eff6ff;
  color: #2563eb;
  display: flex;
  align-items: center;
  justify-content: center;
}

.wiki-brand-title {
  font-size: 18px;
  font-weight: 700;
  color: #111827;
}

.wiki-arrow-btn {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 1px solid #e5e7eb;
  background: #f8fafc;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #64748b;
  transition: all 0.15s ease;
}

.wiki-panel-card:hover .wiki-arrow-btn {
  color: #2563eb;
  border-color: #2563eb;
  transform: translateX(2px);
}

.wiki-intro-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.wiki-headline {
  font-size: 19px;
  font-weight: 800;
  color: #111827;
  letter-spacing: -0.02em;
}

.wiki-desc {
  font-size: 13px;
  line-height: 1.6;
  color: #4b5563;
}

.wiki-features-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
  border-top: 1px solid #f1f5f9;
  padding-top: 16px;
}

.wiki-feature-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.wiki-feature-icon {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 2px;
}

.wiki-feature-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.wiki-feature-title {
  font-size: 14px;
  font-weight: 700;
  color: #111827;
}

.wiki-feature-desc {
  font-size: 12px;
  color: #64748b;
  line-height: 1.45;
}

.wiki-micro-art {
  width: 100%;
  height: 110px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 12px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  overflow: hidden;
}
</style>
