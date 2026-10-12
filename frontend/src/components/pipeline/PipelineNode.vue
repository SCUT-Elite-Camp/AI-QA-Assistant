<script setup lang="ts">
import type { PipelineNodeItem } from './pipelineNodes'

defineProps<{
  node: PipelineNodeItem
  active: boolean
  activeSubId?: string | null
}>()

const emit = defineEmits<{
  (e: 'select', nodeId: string): void
  (e: 'selectSub', nodeId: string, subId: string): void
}>()
</script>

<template>
  <div
    class="pipeline-step-row"
    :class="{ active }"
    @click="emit('select', node.id)"
  >
    <!-- 步骤圆标 -->
    <div class="step-badge">
      {{ node.step }}
    </div>

    <!-- 普通节点卡片 -->
    <div
      v-if="!node.isHighlighted"
      class="node-card"
      :class="{ active }"
    >
      <div
        class="node-icon-box"
        :style="{ background: node.colorBg, color: node.color }"
      >
        <!-- 动态 SVG 图标 -->
        <svg
          v-if="node.icon === 'document'"
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
          v-else-if="node.icon === 'layers'"
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
          v-else-if="node.icon === 'search'"
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>

        <svg
          v-else-if="node.icon === 'database'"
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <ellipse cx="12" cy="5" rx="9" ry="3" />
          <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
          <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
        </svg>
      </div>

      <div class="node-text-group">
        <div class="node-title">{{ node.title }}</div>
        <div class="node-subtitle">{{ node.subtitle }}</div>
      </div>
    </div>

    <!-- 节点 03: 强化 Chunking 双子卡片 -->
    <div
      v-else
      class="node-card chunk-master-card"
      :class="{ active }"
    >
      <div class="chunk-header-row">
        <div
          class="node-icon-box"
          :style="{ background: node.colorBg, color: '#8B5CF6' }"
        >
          <svg
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
            <line x1="9" y1="15" x2="15" y2="15" />
          </svg>
        </div>
        <div class="node-text-group">
          <div class="node-title">{{ node.title }}</div>
          <div class="node-subtitle">{{ node.subtitle }}</div>
        </div>
      </div>

      <!-- 内嵌子卡片 -->
      <div class="chunk-subgrid" v-if="node.subtracks">
        <div
          v-for="sub in node.subtracks"
          :key="sub.id"
          class="chunk-subcard"
          :class="[sub.id === 'chunk-evidence' ? 'evidence' : 'section', { active: activeSubId === sub.id }]"
          @click.stop="emit('selectSub', node.id, sub.id)"
        >
          <div class="chunk-subicon">
            <svg
              v-if="sub.id === 'chunk-evidence'"
              width="16"
              height="16"
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
              v-else
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <circle cx="18" cy="5" r="3" />
              <circle cx="6" cy="12" r="3" />
              <circle cx="18" cy="19" r="3" />
              <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
              <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
            </svg>
          </div>
          <div class="chunk-subtext">
            <span class="chunk-subtitle-main">{{ sub.name }}</span>
            <span class="chunk-subdesc">{{ sub.label }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 右侧注释标注与虚线连接 -->
    <div class="node-callout-wrap">
      <div class="callout-line"></div>
      <div class="callout-text">{{ node.callout }}</div>
    </div>
  </div>
</template>

<style scoped>
.pipeline-step-row {
  display: grid;
  grid-template-columns: 36px 360px 1fr;
  gap: 14px;
  align-items: center;
  width: 100%;
  position: relative;
  cursor: pointer;
}

.step-badge {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 1.5px solid #d1d5db;
  background: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-mono, monospace);
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  flex-shrink: 0;
  transition: all 0.2s ease;
}

.pipeline-step-row:hover .step-badge,
.pipeline-step-row.active .step-badge {
  border-color: #2563eb;
  color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

.node-card {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  padding: 12px 18px;
  display: flex;
  align-items: center;
  gap: 14px;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.03);
}

.node-card:hover {
  border-color: #cbd5e1;
  transform: translateY(-2px);
  box-shadow: 0 4px 16px -2px rgba(15, 23, 42, 0.06);
}

.node-card.active {
  border-color: #2563eb;
  box-shadow: 0 6px 20px rgba(37, 99, 235, 0.12);
  transform: translateY(-2px);
}

.node-icon-box {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: transform 0.2s ease;
}

.node-card:hover .node-icon-box {
  transform: scale(1.05);
}

.node-text-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
}

.node-title {
  font-size: 15px;
  font-weight: 700;
  color: #111827;
  letter-spacing: -0.01em;
}

.node-subtitle {
  font-size: 12px;
  color: #64748b;
  font-family: var(--font-mono, monospace);
  font-weight: 400;
}

.node-callout-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  position: relative;
}

.callout-line {
  width: 24px;
  height: 1px;
  border-top: 1.5px dashed #cbd5e1;
  flex-shrink: 0;
}

.callout-text {
  font-size: 11.5px;
  line-height: 1.55;
  color: #64748b;
  white-space: pre-line;
}

/* 节点 03 强化大卡片 */
.node-card.chunk-master-card {
  padding: 16px 20px;
  flex-direction: column;
  align-items: flex-start;
  gap: 14px;
  background: #fafbff;
  border: 1.5px solid #dbeafe;
}

.node-card.chunk-master-card.active {
  border-color: #2563eb;
  background: #ffffff;
}

.chunk-header-row {
  display: flex;
  align-items: center;
  gap: 14px;
  width: 100%;
}

.chunk-subgrid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  width: 100%;
}

.chunk-subcard {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 10px 12px;
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

.chunk-subcard:hover {
  transform: translateY(-1.5px);
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.03);
}

.chunk-subcard.evidence {
  border-color: #bfdbfe;
  background: #eff6ff;
}

.chunk-subcard.evidence:hover,
.chunk-subcard.evidence.active {
  border-color: #2563eb;
  background: #ffffff;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.15);
}

.chunk-subcard.section {
  border-color: #bbf7d0;
  background: #f0fdf4;
}

.chunk-subcard.section:hover,
.chunk-subcard.section.active {
  border-color: #10b981;
  background: #ffffff;
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.15);
}

.chunk-subicon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.chunk-subcard.evidence .chunk-subicon {
  background: #dbeafe;
  color: #2563eb;
}

.chunk-subcard.section .chunk-subicon {
  background: #dcfce7;
  color: #10b981;
}

.chunk-subtext {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.chunk-subtitle-main {
  font-size: 13.5px;
  font-weight: 700;
  color: #111827;
  letter-spacing: -0.01em;
}

.chunk-subdesc {
  font-size: 11.5px;
  color: #64748b;
}
</style>
