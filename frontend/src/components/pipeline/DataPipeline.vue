<script setup lang="ts">
import { ref } from 'vue'
import {
  pipelineNodes,
  wikiPanelData,
  designDecisions,
  leftFeatures,
  type DetailPayload
} from './pipelineNodes'
import PipelineNode from './PipelineNode.vue'
import WikiPanel from './WikiPanel.vue'
import DesignDecisionCard from './DesignDecisionCard.vue'

// 当前展开的实体与详情
const activeEntityId = ref<string | null>(null)
const activeSubtrackId = ref<string | null>(null)
const isDrawerOpen = ref(false)
const drawerBadge = ref('PIPELINE')
const drawerDetail = ref<DetailPayload | null>(null)

function openNode(nodeId: string) {
  const node = pipelineNodes.find(n => n.id === nodeId)
  if (!node) return
  if (activeEntityId.value === nodeId && !activeSubtrackId.value && isDrawerOpen.value) {
    closeDrawer()
    return
  }
  activeEntityId.value = nodeId
  activeSubtrackId.value = null
  drawerBadge.value = `NODE ${node.step}`
  drawerDetail.value = node.details
  isDrawerOpen.value = true
}

function openSubtrack(nodeId: string, subId: string) {
  const node = pipelineNodes.find(n => n.id === nodeId)
  if (!node || !node.subtracks) return
  const sub = node.subtracks.find(s => s.id === subId)
  if (!sub) return
  if (activeSubtrackId.value === subId && isDrawerOpen.value) {
    closeDrawer()
    return
  }
  activeEntityId.value = nodeId
  activeSubtrackId.value = subId
  drawerBadge.value = `CHUNKING · ${sub.name.toUpperCase()}`
  drawerDetail.value = sub.details
  isDrawerOpen.value = true
}

function openWiki() {
  if (activeEntityId.value === 'wiki' && isDrawerOpen.value) {
    closeDrawer()
    return
  }
  activeEntityId.value = 'wiki'
  activeSubtrackId.value = null
  drawerBadge.value = 'WIKI LAYER'
  drawerDetail.value = wikiPanelData.details
  isDrawerOpen.value = true
}

function openDecision(decisionId: string) {
  const decision = designDecisions.find(d => d.id === decisionId)
  if (!decision) return
  if (activeEntityId.value === decisionId && isDrawerOpen.value) {
    closeDrawer()
    return
  }
  activeEntityId.value = decisionId
  activeSubtrackId.value = null
  drawerBadge.value = `DECISION ${decision.step}`
  drawerDetail.value = decision.details
  isDrawerOpen.value = true
}

function closeDrawer() {
  isDrawerOpen.value = false
  activeEntityId.value = null
  activeSubtrackId.value = null
}
</script>

<template>
  <div class="data-pipeline-root">
    <!-- 主体区域: 三栏横向网格 (左侧说明 / 中间 Pipeline 流程 / 右侧 Wiki 概念层) -->
    <section class="pipeline-hero-grid">
      <!-- 左栏: 章节标题与四大特征要点 -->
      <div class="col-left">
        <div>
          <div class="chapter-eyebrow">02 / DATA PIPELINE</div>
          <h1 class="chapter-title">
            从原始文档，<br />
            <span class="accent-blue">到结构化知识资产</span>
          </h1>
          <p class="chapter-subtitle">
            通过自动化的数据处理流水线，将分散在 PDF、Word、Confluence 等多源异构文档，转化为可检索、可验证、可持续更新的知识资产。
          </p>
        </div>

        <div class="pillar-points">
          <div
            v-for="(feature, idx) in leftFeatures"
            :key="idx"
            class="pillar-item"
          >
            <div class="pillar-icon-box" :style="{ color: feature.color }">
              <svg
                v-if="feature.icon === 'document'"
                width="18"
                height="18"
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
                v-else-if="feature.icon === 'layers'"
                width="18"
                height="18"
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
                v-else-if="feature.icon === 'refresh'"
                width="18"
                height="18"
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

              <svg
                v-else-if="feature.icon === 'shield-check'"
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                <polyline points="9 12 11 14 15 10" />
              </svg>
            </div>
            <div class="pillar-text-group">
              <span class="pillar-heading">{{ feature.title }}</span>
              <span class="pillar-desc">{{ feature.desc }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 中栏: 纵向流水线主流程 -->
      <div class="col-center-pipeline">
        <template v-for="(node, index) in pipelineNodes" :key="node.id">
          <PipelineNode
            :node="node"
            :active="activeEntityId === node.id"
            :active-sub-id="activeEntityId === node.id ? activeSubtrackId : null"
            @select="openNode"
            @select-sub="openSubtrack"
          />

          <!-- 步骤间连线与双向箭头 -->
          <div v-if="index < pipelineNodes.length - 1" class="step-connector">
            <div class="connector-symbol">↕</div>
          </div>
        </template>
      </div>

      <!-- 右栏: Wiki 概念层 (特色入口独立面板) -->
      <div class="col-right-wiki">
        <WikiPanel
          :data="wikiPanelData"
          :active="activeEntityId === 'wiki'"
          @select="openWiki"
        />
      </div>
    </section>

    <!-- 技术详情抽屉 (Progressive Interactive Tech Drawer) -->
    <div
      v-if="isDrawerOpen && drawerDetail"
      class="tech-detail-drawer"
    >
      <div class="detail-drawer-header">
        <div class="detail-drawer-title-group">
          <span class="detail-drawer-badge">{{ drawerBadge }}</span>
          <h3 class="detail-drawer-title">{{ drawerDetail.name }}</h3>
        </div>
        <button class="detail-drawer-close" aria-label="关闭详情" @click="closeDrawer">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>

      <div class="detail-drawer-grid">
        <div class="detail-drawer-cell">
          <span class="detail-cell-label">Why / 背景与痛点</span>
          <p class="detail-cell-content">{{ drawerDetail.why }}</p>
        </div>
        <div class="detail-drawer-cell">
          <span class="detail-cell-label">Design / 设计方案</span>
          <p class="detail-cell-content">{{ drawerDetail.design }}</p>
        </div>
        <div class="detail-drawer-cell">
          <span class="detail-cell-label">Technology / 核心技术</span>
          <p class="detail-cell-content">{{ drawerDetail.technology }}</p>
        </div>
        <div class="detail-drawer-cell">
          <span class="detail-cell-label">IO / 输入输出规约</span>
          <p class="detail-cell-content">{{ drawerDetail.io }}</p>
        </div>
      </div>
    </div>

    <!-- 底部三大核心设计决策 Section -->
    <section class="decisions-section">
      <div class="decisions-header">
        <div class="decisions-meta">
          <span class="decisions-eyebrow">KEY DESIGN DECISIONS</span>
          <h2 class="decisions-title">三大核心设计</h2>
        </div>
        <a href="#explore" class="decisions-more-link" @click.prevent="openNode('node-03')">
          <span>探索完整技术细节</span>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M5 12h14" />
            <path d="m12 5 7 7-7 7" />
          </svg>
        </a>
      </div>

      <div class="decisions-grid">
        <DesignDecisionCard
          v-for="decision in designDecisions"
          :key="decision.id"
          :decision="decision"
          :active="activeEntityId === decision.id"
          @select="openDecision"
        />
      </div>
    </section>
  </div>
</template>

<style scoped>
.data-pipeline-root {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 36px;
}

.pipeline-hero-grid {
  display: grid;
  grid-template-columns: 290px 580px 1fr;
  gap: 36px;
  align-items: flex-start;
  min-height: 540px;
  position: relative;
}

.col-left {
  display: flex;
  flex-direction: column;
  gap: 28px;
  padding-top: 8px;
}

.chapter-eyebrow {
  font-family: var(--font-mono, monospace);
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #64748b;
  margin-bottom: 12px;
}

.chapter-title {
  font-size: 38px;
  line-height: 1.25;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: #111827;
}

.chapter-title .accent-blue {
  color: #2563eb;
}

.chapter-subtitle {
  font-size: 14px;
  line-height: 1.65;
  color: #4b5563;
  margin-top: 4px;
  font-weight: 400;
}

.pillar-points {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-top: 4px;
}

.pillar-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.pillar-icon-box {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.03);
}

.pillar-text-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.pillar-heading {
  font-size: 14px;
  font-weight: 600;
  color: #111827;
  letter-spacing: -0.01em;
}

.pillar-desc {
  font-size: 12px;
  line-height: 1.5;
  color: #64748b;
}

.col-center-pipeline {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  position: relative;
}

.step-connector {
  width: 100%;
  display: grid;
  grid-template-columns: 36px 360px 1fr;
  gap: 14px;
  height: 28px;
  align-items: center;
  position: relative;
}

.connector-symbol {
  grid-column: 2;
  display: flex;
  justify-content: center;
  color: #94a3b8;
  font-size: 15px;
  line-height: 1;
}

.col-right-wiki {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* 详情抽屉 */
.tech-detail-drawer {
  width: 100%;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 24px 28px;
  box-shadow: 0 4px 16px -2px rgba(15, 23, 42, 0.06);
  margin-top: -6px;
  animation: fadeInSlide 0.24s ease-out;
}

@keyframes fadeInSlide {
  from {
    opacity: 0;
    transform: translateY(-8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.detail-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #e5e7eb;
  padding-bottom: 14px;
  margin-bottom: 16px;
}

.detail-drawer-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}

.detail-drawer-badge {
  font-family: var(--font-mono, monospace);
  font-size: 12px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 4px;
  background: #eff6ff;
  color: #2563eb;
}

.detail-drawer-title {
  font-size: 17px;
  font-weight: 700;
  color: #111827;
}

.detail-drawer-close {
  background: transparent;
  border: none;
  cursor: pointer;
  color: #64748b;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 4px;
  border-radius: 4px;
}

.detail-drawer-close:hover {
  background: #f1f5f9;
  color: #111827;
}

.detail-drawer-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
}

.detail-drawer-cell {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.detail-cell-label {
  font-family: var(--font-mono, monospace);
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.detail-cell-content {
  font-size: 12.5px;
  line-height: 1.6;
  color: #111827;
}

/* 底部决策 */
.decisions-section {
  width: 100%;
  border-top: 1px solid #e5e7eb;
  padding-top: 36px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.decisions-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
}

.decisions-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.decisions-eyebrow {
  font-family: var(--font-mono, monospace);
  font-size: 11.5px;
  font-weight: 600;
  color: #64748b;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.decisions-title {
  font-size: 24px;
  font-weight: 800;
  letter-spacing: -0.02em;
  color: #111827;
}

.decisions-more-link {
  font-size: 13.5px;
  font-weight: 600;
  color: #4b5563;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.decisions-more-link:hover {
  color: #2563eb;
  transform: translateX(2px);
}

.decisions-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
}

@media (max-width: 1200px) {
  .pipeline-hero-grid {
    grid-template-columns: 260px 520px 1fr;
    gap: 24px;
  }
  .detail-drawer-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 1024px) {
  .pipeline-hero-grid {
    grid-template-columns: 1fr;
  }
  .decisions-grid {
    grid-template-columns: 1fr;
  }
}
</style>
