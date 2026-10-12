<script setup lang="ts">
import { computed, provide, ref } from 'vue'
import type { ResearchEvent, ResearchJob, ResearchPlan, ResearchProgress, ResearchReport } from '../../types/research'
import ChatComark from '../chat/Comark'
import ResearchMessageActions from './ResearchMessageActions.vue'
import ResearchSources from './ResearchSources.vue'
import ModalDocumentViewer from '../chat/ModalDocumentViewer.vue'
import type { ChunkCitation } from '../chat/tool/Sources.vue'
import { formatResearchCitations } from '../../utils/researchMarkdown'
import { researchSourceHref } from '../../utils/research'

const props = defineProps<{ job: ResearchJob, report: ResearchReport, plan?: ResearchPlan | null, progress?: ResearchProgress | null, events?: ResearchEvent[] }>()
const emit = defineEmits<{ restart: [], askSelectedText: [text: string], regenerate: [] }>()
const useMock = import.meta.env.VITE_RESEARCH_USE_MOCK === 'true'
const downloadHref = computed(() => `/api/research/download?researchId=${encodeURIComponent(props.job.research_id)}`)
const sourceOpen = ref(false)
const selectedSource = ref<ChunkCitation | null>(null)
const selectedText = ref('')
const selectionPosition = ref<{ x: number, y: number } | null>(null)
const latestRecovery = computed(() => [...(props.events ?? [])].reverse().find(event => event.event_type === 'job_recovered'))
const reportMarkdown = computed(() => formatResearchCitations(props.report.markdown
  .replace(/^#\s+[^\n]+\n+/, '')
  .replace(/\n##\s+来源\s*\n[\s\S]*$/u, '')))
const sourceCitations = computed<ChunkCitation[]>(() => props.report.citations.map(citation => ({
    index: citation.number,
    doc_id: citation.doc_id,
    chunk_id: citation.evidence_id,
    title: citation.title,
    source_url: researchSourceHref(props.job.research_id, citation.doc_id),
    chunk_text: citation.excerpt,
    anchor_excerpt: citation.anchor_excerpt,
    content_hash: citation.content_hash,
    normalized_content_hash: citation.content_hash,
    source_version: citation.document_version ?? undefined,
    locator: { chunk_id: citation.locator },
})))
const citationMap = computed(() => new Map(sourceCitations.value.map(citation => [citation.index, citation])))

provide('ragCitationMap', citationMap)
provide('openCitation', (index: number) => {
  const citation = citationMap.value.get(index)
  if (citation) { selectedSource.value = citation; sourceOpen.value = true }
})

function downloadMarkdown() {
  const blob = new Blob([props.report.markdown], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${props.report.report_id}.md`
  link.hidden = true
  document.body.appendChild(link)
  link.click()
  link.remove()
  // Keep the blob alive until the browser has consumed the download request.
  // Immediate revocation can cancel an asynchronous download.
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
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
    <ModalDocumentViewer v-model:open="sourceOpen" :doc="selectedSource" :research-id="job.research_id" />
    <p class="max-w-[72ch] text-base leading-7 text-highlighted">
      Research is complete. The findings below include verified evidence and source citations<span v-if="report.conflicts?.length">; source conflicts require your review</span><span v-else-if="report.result_status !== 'complete'">; some findings need confirmation or did not pass quality checks. Review the limitations</span>.
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
        Copy
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
        Ask about selection
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
            Conflict review
          </h2>
          <p class="mt-1 text-sm text-muted">
            Original statements from each source and resolution reasons are recorded separately.
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
              :label="conflict.conflict_type === 'version' ? 'Version conflict' : conflict.conflict_type === 'numeric' ? 'Numeric conflict' : 'Source conflict'"
            />
            <UBadge
              :color="conflict.resolution_status !== 'unresolved' ? 'success' : 'neutral'"
              variant="soft"
              :label="conflict.resolution_status === 'resolved_by_user' ? 'Resolved by you' : conflict.resolution_status === 'resolved_by_authority' ? 'Resolution recorded' : 'Needs review'"
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
                    Version:
                  </dt><dd class="inline">
                    {{ alternative.document_version || 'Not recorded' }}
                  </dd>
                </div>
                <div>
                  <dt class="inline">
                    Updated:
                  </dt><dd class="inline">
                    {{ alternative.updated_at || alternative.effective_at || 'Not recorded' }}
                  </dd>
                </div>
                <div>
                  <dt class="inline">
                    Authority:
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
      text="Knowledge base sources"
      :suffix="`${sourceCitations.length} evidence items`"
      :streaming="false"
      chevron="leading"
      class="max-w-[72ch]"
    >
      <ResearchSources
        :citations="report.citations"
        :research-id="job.research_id"
      />
    </UChatTool>

    <section
      v-if="progress"
      class="border-t border-default pt-5"
    >
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h2 class="font-semibold text-highlighted">
          Execution summary
        </h2>
        <UBadge
          v-if="latestRecovery"
          color="primary"
          variant="soft"
          icon="i-lucide-history"
          label="Restored from checkpoint"
        />
      </div>
      <dl class="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
        <div>
          <dt class="text-xs text-muted">
            Elapsed time
          </dt><dd class="mt-1 font-semibold text-highlighted">
            {{ (progress.metrics.elapsed_ms / 1000).toFixed(1) }} seconds
          </dd>
        </div>
        <div>
          <dt class="text-xs text-muted">
            Actions used
          </dt><dd class="mt-1 font-semibold text-highlighted">
            {{ progress.metrics.actions_used }} / {{ plan?.budget?.max_actions ?? '—' }}
          </dd>
        </div>
        <div>
          <dt class="text-xs text-muted">
            Documents read
          </dt><dd class="mt-1 font-semibold text-highlighted">
            {{ progress.metrics.documents_read }}
          </dd>
        </div>
        <div>
          <dt class="text-xs text-muted">
            Recoveries
          </dt><dd class="mt-1 font-semibold text-highlighted">
            {{ progress.metrics.recovery_count }}
          </dd>
        </div>
      </dl>
      <p
        v-if="latestRecovery"
        class="mt-4 text-xs leading-5 text-muted"
      >
        Restored from checkpoint. Recovery did not duplicate evidence or reports.
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
        <a v-if="!useMock" :href="downloadHref" :download="`${report.report_id}.md`" class="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-muted hover:bg-elevated hover:text-highlighted">
          <UIcon name="i-lucide-download" class="size-4" />Download
        </a>
        <UButton
          v-else
          color="neutral"
          variant="ghost"
          size="sm"
          icon="i-lucide-download"
          label="Download"
          @click="downloadMarkdown"
        />
      </div>
      <div class="ml-auto flex items-center gap-1 text-xs text-muted">
        <span>{{ report.result_status === 'complete' ? 'Research complete' : 'Needs review' }}</span>
        <span aria-hidden="true">·</span>
        <time :datetime="report.generated_at">{{ new Date(report.generated_at).toLocaleString() }}</time>
      </div>
      <UButton
        class="basis-full justify-start"
        color="neutral"
        variant="ghost"
        size="sm"
        icon="i-lucide-rotate-ccw"
        label="Start new research"
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
