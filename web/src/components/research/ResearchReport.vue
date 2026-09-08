<script setup lang="ts">
import { computed, provide, ref } from 'vue'
import type { ResearchEvent, ResearchJob, ResearchPlan, ResearchProgress, ResearchReport } from '../../types/research'
import ChatComark from '../chat/Comark'
import ResearchMessageActions from './ResearchMessageActions.vue'
import ResearchSources from './ResearchSources.vue'
import type { ChunkCitation } from '../chat/tool/Sources.vue'

const props = defineProps<{ job: ResearchJob, report: ResearchReport, plan?: ResearchPlan | null, progress?: ResearchProgress | null, events?: ResearchEvent[] }>()
const emit = defineEmits<{ restart: [], askSelectedText: [text: string], regenerate: [] }>()
const selectedText = ref('')
const selectionPosition = ref<{ x: number, y: number } | null>(null)
const latestRecovery = computed(() => [...(props.events ?? [])].reverse().find(event => event.event_type === 'job_recovered'))
const reportMarkdown = computed(() => props.report.markdown
  .replace(/^#\s+[^\n]+\n+/, '')
  .replace(/\n##\s+来源\s*\n[\s\S]*$/u, '')
  .replace(/\[(\d+)]/g, '<cite-mark index="$1"></cite-mark>'))
const sourceCitations = computed<ChunkCitation[]>(() => props.report.citations.map(citation => ({
    index: citation.number,
    doc_id: citation.doc_id,
    chunk_id: citation.evidence_id,
    title: citation.title,
    source_url: citation.source_url ?? undefined,
    chunk_text: citation.excerpt,
})))
const citationMap = computed(() => new Map(sourceCitations.value.map(citation => [citation.index, citation])))

provide('ragCitationMap', citationMap)

function downloadMarkdown() {
  const blob = new Blob([props.report.markdown], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${props.report.report_id}.md`
  link.click()
  URL.revokeObjectURL(url)
}

function handleTextSelection() {
  window.setTimeout(() => {
    const selection = window.getSelection()
    const text = selection?.toString().trim() ?? ''
    const range = text && selection?.rangeCount ? selection.getRangeAt(0) : null
    const rect = range?.getBoundingClientRect()
    if (text.length > 1 && rect) {
      selectedText.value = text
      selectionPosition.value = { x: rect.left + rect.width / 2, y: rect.top - 8 }
    } else selectionPosition.value = null
  }, 20)
}

async function copySelectedText() {
  if (!selectedText.value) return
  await navigator.clipboard.writeText(selectedText.value)
  selectionPosition.value = null
  window.getSelection()?.removeAllRanges()
}

function askSelectedText() {
  if (!selectedText.value) return
  emit('askSelectedText', selectedText.value)
  selectionPosition.value = null
  window.getSelection()?.removeAllRanges()
}
</script>

<template>
  <div class="space-y-6">
    <p class="max-w-[72ch] text-base leading-7 text-highlighted">
      研究已经完成。以下结论来自已核验的资料与原文引用<span v-if="report.result_status !== 'complete'">；其中仍有资料冲突，需要你结合实际情况复核</span>。
    </p>

    <article
      class="research-answer max-w-[72ch] text-base leading-7 text-highlighted"
      @mouseup="handleTextSelection"
    >
      <ChatComark
        :markdown="reportMarkdown"
        :streaming="false"
      />
    </article>

    <div
      v-if="selectionPosition && selectedText"
      class="float-selection-pill fixed z-50 flex -translate-x-1/2 -translate-y-full items-center gap-1 rounded-full border border-zinc-700/60 bg-zinc-900/95 p-1 text-white shadow-xl"
      :style="{ left: `${selectionPosition.x}px`, top: `${selectionPosition.y}px` }"
      @pointerdown.stop
    >
      <button
        type="button"
        class="flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs text-zinc-300 transition-colors hover:bg-zinc-700/60 hover:text-white"
        @pointerdown.stop="copySelectedText"
      >
        <UIcon
          name="i-lucide-copy"
          class="size-3.5"
        />
        复制
      </button>
      <span class="h-3.5 w-px bg-zinc-700/60" />
      <button
        type="button"
        class="flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs text-zinc-200 transition-colors hover:bg-zinc-700/60 hover:text-white"
        @pointerdown.stop="askSelectedText"
      >
        <UIcon
          name="i-lucide-message-circle-question"
          class="size-3.5"
        />
        划词提问
      </button>
    </div>

    <section
      v-if="report.conflicts?.length"
      class="border-y border-default py-5 sm:py-6"
    >
      <div class="flex items-start gap-3">
        <UIcon
          name="i-lucide-git-compare-arrows"
          class="mt-0.5 size-5 shrink-0 text-warning"
        />
        <div>
          <h2 class="font-semibold text-highlighted">
            冲突核验
          </h2>
          <p class="mt-1 text-sm text-muted">
            系统保留了不同来源的原始说法，并单独记录处理依据。
          </p>
        </div>
      </div>
      <div class="mt-4 space-y-4">
        <article
          v-for="conflict in report.conflicts"
          :key="conflict.conflict_id"
          class="border-t border-default py-4 first:border-t-0"
        >
          <div class="flex flex-wrap items-center gap-2">
            <UBadge
              color="warning"
              variant="soft"
              :label="conflict.conflict_type === 'version' ? '版本冲突' : conflict.conflict_type === 'numeric' ? '数值冲突' : '来源冲突'"
            />
            <UBadge
              :color="conflict.resolution_status !== 'unresolved' ? 'success' : 'neutral'"
              variant="soft"
              :label="conflict.resolution_status === 'resolved_by_user' ? '已由你确认' : conflict.resolution_status === 'resolved_by_authority' ? '已有处理依据' : '需要人工复核'"
            />
          </div>
          <p class="mt-3 text-sm leading-6 text-highlighted">
            {{ conflict.summary }}
          </p>
          <ul class="mt-3 grid gap-3 sm:grid-cols-2">
            <li
              v-for="alternative in conflict.alternatives"
              :key="alternative.evidence_id"
              class="min-w-0 rounded-lg border border-default bg-elevated px-4 py-3 text-sm text-muted"
            >
              <p class="font-medium text-highlighted">
                [{{ alternative.citation_number }}] {{ alternative.source_title }}
              </p>
              <p class="mt-2 whitespace-pre-wrap break-words leading-6 text-highlighted">
                {{ alternative.value_summary }}
              </p>
              <dl class="mt-3 space-y-1 text-xs">
                <div>
                  <dt class="inline">
                    版本：
                  </dt><dd class="inline">
                    {{ alternative.document_version || '未标注' }}
                  </dd>
                </div>
                <div>
                  <dt class="inline">
                    更新时间：
                  </dt><dd class="inline">
                    {{ alternative.updated_at || alternative.effective_at || '未标注' }}
                  </dd>
                </div>
                <div>
                  <dt class="inline">
                    权威等级：
                  </dt><dd class="inline">
                    {{ alternative.authority }}（{{ alternative.authority_rank }}）
                  </dd>
                </div>
              </dl>
            </li>
          </ul>
          <p
            v-if="conflict.resolution"
            class="mt-3 text-sm text-success"
          >
            {{ conflict.resolution }}
          </p>
        </article>
      </div>
    </section>

    <UChatTool
      v-if="sourceCitations.length"
      text="已检索知识库"
      :suffix="`${sourceCitations.length} 条证据`"
      :streaming="false"
      chevron="leading"
      class="max-w-[72ch]"
    >
      <ResearchSources :citations="report.citations" />
    </UChatTool>

    <section
      v-if="progress"
      class="border-t border-default pt-5"
    >
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h2 class="font-semibold text-highlighted">
          执行记录
        </h2>
        <UBadge
          v-if="latestRecovery"
          color="primary"
          variant="soft"
          icon="i-lucide-history"
          label="已从检查点恢复"
        />
      </div>
      <dl class="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
        <div>
          <dt class="text-xs text-muted">
            执行耗时
          </dt><dd class="mt-1 font-semibold text-highlighted">
            {{ (progress.metrics.elapsed_ms / 1000).toFixed(1) }} 秒
          </dd>
        </div>
        <div>
          <dt class="text-xs text-muted">
            动作使用
          </dt><dd class="mt-1 font-semibold text-highlighted">
            {{ progress.metrics.actions_used }} / {{ plan?.budget?.max_actions ?? '—' }}
          </dd>
        </div>
        <div>
          <dt class="text-xs text-muted">
            读取资料
          </dt><dd class="mt-1 font-semibold text-highlighted">
            {{ progress.metrics.documents_read }}
          </dd>
        </div>
        <div>
          <dt class="text-xs text-muted">
            恢复次数
          </dt><dd class="mt-1 font-semibold text-highlighted">
            {{ progress.metrics.recovery_count }}
          </dd>
        </div>
      </dl>
      <p
        v-if="latestRecovery"
        class="mt-4 text-xs leading-5 text-muted"
      >
        {{ latestRecovery.message }}，恢复过程未重复写入证据或报告。
      </p>
    </section>

    <div class="flex flex-wrap items-center gap-3 border-t border-default pt-4">
      <div class="flex items-center gap-1">
        <ResearchMessageActions
          :chat-id="job.research_id"
          :message-id="`research-report-${report.report_id}`"
          :text="report.markdown"
          :created-at="report.generated_at"
          @regenerate="emit('regenerate')"
        />
        <UButton
          color="neutral"
          variant="ghost"
          size="sm"
          icon="i-lucide-download"
          label="下载"
          @click="downloadMarkdown"
        />
      </div>
      <div class="ml-auto flex items-center gap-1 text-xs text-muted">
        <span>{{ report.result_status === 'complete' ? '研究完成' : '需要复核' }}</span>
        <span aria-hidden="true">·</span>
        <time :datetime="report.generated_at">{{ new Date(report.generated_at).toLocaleString() }}</time>
      </div>
      <UButton
        class="basis-full justify-start"
        color="neutral"
        variant="ghost"
        size="sm"
        icon="i-lucide-rotate-ccw"
        label="发起新的研究"
        @click="emit('restart')"
      />
    </div>
  </div>
</template>

<style scoped>
.research-answer :deep(.markdown-body) {
  font-size: 1rem;
  line-height: 1.75;
}

.research-answer :deep(.markdown-body h1) {
  margin: 0 0 1rem;
  font-size: 1.375rem;
  line-height: 1.4;
  letter-spacing: -0.015em;
}

.research-answer :deep(.markdown-body h2) {
  margin-top: 1.75rem;
  margin-bottom: 0.625rem;
  padding-bottom: 0;
  border-bottom: 0;
  font-size: 1.125rem;
  line-height: 1.5;
}

.research-answer :deep(.markdown-body h3) {
  margin-top: 1.375rem;
  font-size: 1rem;
  line-height: 1.6;
}
</style>
