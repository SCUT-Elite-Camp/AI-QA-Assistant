<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ResearchCitation, ResearchEvent, ResearchJob, ResearchPlan, ResearchProgress, ResearchReport } from '../../types/research'
import ChatComark from '../chat/Comark'

const props = defineProps<{ job: ResearchJob, report: ResearchReport, plan?: ResearchPlan | null, progress?: ResearchProgress | null, events?: ResearchEvent[] }>()
const emit = defineEmits<{ restart: [] }>()
const citationOpen = ref(false)
const selectedCitation = ref<ResearchCitation | null>(null)
const latestRecovery = computed(() => [...(props.events ?? [])].reverse().find(event => event.event_type === 'job_recovered'))

function openCitation(citation: ResearchCitation) {
  selectedCitation.value = citation
  citationOpen.value = true
}

async function copyReport() {
  await navigator.clipboard.writeText(props.report.markdown)
  useToast().add({ title: '报告已复制', color: 'success' })
}

function downloadMarkdown() {
  const blob = new Blob([props.report.markdown], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${props.report.report_id}.md`
  link.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <div class="space-y-6">
    <section
      class="rounded-2xl border p-6 sm:p-8"
      :class="report.result_status === 'complete' ? 'border-success/30 bg-success/5' : 'border-warning/30 bg-warning/5'"
    >
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div class="flex items-start gap-3">
          <span
            class="flex size-11 shrink-0 items-center justify-center rounded-full"
            :class="report.result_status === 'complete' ? 'bg-success/15 text-success' : 'bg-warning/15 text-warning'"
          >
            <UIcon
              :name="report.result_status === 'complete' ? 'i-lucide-check-check' : 'i-lucide-triangle-alert'"
              class="size-6"
            />
          </span>
          <div>
            <p
              class="text-xs font-semibold uppercase tracking-wider"
              :class="report.result_status === 'complete' ? 'text-success' : 'text-warning'"
            >
              {{ report.result_status === 'complete' ? '研究完成' : '研究完成 · 需要复核' }}
            </p><h2 class="mt-1 text-2xl font-bold text-highlighted">
              {{ job.request.report_spec.title || 'Deep Research 报告' }}
            </h2><p class="mt-2 text-sm text-muted">
              {{ job.request.query }}
            </p>
          </div>
        </div>
        <div class="flex gap-2">
          <UButton
            color="neutral"
            variant="soft"
            icon="i-lucide-copy"
            label="复制"
            @click="copyReport"
          /><UButton
            color="neutral"
            variant="soft"
            icon="i-lucide-download"
            label="下载 Markdown"
            @click="downloadMarkdown"
          />
        </div>
      </div>
      <div class="mt-5">
        <UBadge
          color="neutral"
          variant="soft"
          :label="new Date(report.generated_at).toLocaleString()"
        />
      </div>
    </section>

    <article class="rounded-xl border border-default bg-default p-6 shadow-sm sm:p-8">
      <ChatComark
        :markdown="report.markdown"
        :streaming="false"
      />
    </article>

    <section
      v-if="report.conflicts?.length"
      class="rounded-xl border border-warning/30 bg-warning/5 p-5 sm:p-6"
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
          class="rounded-lg border border-default bg-default p-4"
        >
          <div class="flex flex-wrap items-center gap-2">
            <UBadge
              color="warning"
              variant="soft"
              :label="conflict.conflict_type === 'version' ? '版本冲突' : conflict.conflict_type === 'numeric' ? '数值冲突' : '来源冲突'"
            />
            <UBadge
              :color="conflict.resolution_status === 'resolved_by_authority' ? 'success' : 'neutral'"
              variant="soft"
              :label="conflict.resolution_status === 'resolved_by_authority' ? '已有处理依据' : '需要人工复核'"
            />
          </div>
          <p class="mt-3 text-sm leading-6 text-highlighted">
            {{ conflict.summary }}
          </p>
          <ul class="mt-3 space-y-2">
            <li
              v-for="alternative in conflict.alternatives"
              :key="alternative.evidence_id"
              class="rounded-md bg-elevated px-3 py-2 text-sm text-muted"
            >
              <span class="font-medium text-highlighted">[{{ alternative.citation_number }}] {{ alternative.source_title }}</span>
              <span v-if="alternative.document_version"> · {{ alternative.document_version }}</span>
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

    <section
      v-if="report.citations?.length"
      class="rounded-xl border border-default bg-default p-5 sm:p-6"
    >
      <div class="flex items-end justify-between gap-4">
        <div>
          <h2 class="font-semibold text-highlighted">
            引用与原文
          </h2>
          <p class="mt-1 text-sm text-muted">
            打开引用可核对原始段落、版本和生效时间。
          </p>
        </div>
        <span class="text-xs text-muted">{{ report.citations.length }} 条</span>
      </div>
      <div class="mt-4 grid gap-3 sm:grid-cols-2">
        <button
          v-for="citation in report.citations"
          :key="citation.evidence_id"
          type="button"
          class="min-h-20 rounded-lg border border-default p-4 text-left transition hover:border-primary/40 hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          @click="openCitation(citation)"
        >
          <div class="flex items-start justify-between gap-3">
            <span class="font-medium text-highlighted">[{{ citation.number }}] {{ citation.title }}</span>
            <UIcon
              name="i-lucide-external-link"
              class="mt-0.5 shrink-0 text-muted"
            />
          </div>
          <p class="mt-2 text-xs text-muted">
            {{ citation.document_version || '未标注版本' }} · {{ citation.locator }}
          </p>
        </button>
      </div>
    </section>

    <section
      v-if="progress"
      class="rounded-xl border border-default bg-elevated/30 p-5"
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

    <div class="flex justify-end">
      <UButton
        color="neutral"
        variant="outline"
        icon="i-lucide-rotate-ccw"
        label="发起新的研究"
        @click="emit('restart')"
      />
    </div>

    <UModal
      v-model:open="citationOpen"
      :title="selectedCitation ? `[${selectedCitation.number}] ${selectedCitation.title}` : '引用原文'"
    >
      <template #content>
        <div
          v-if="selectedCitation"
          class="space-y-5 p-6"
        >
          <div class="flex flex-wrap gap-2">
            <UBadge
              color="neutral"
              variant="soft"
              :label="selectedCitation.source_type"
            />
            <UBadge
              color="neutral"
              variant="soft"
              :label="selectedCitation.document_version || '未标注版本'"
            />
            <UBadge
              v-if="selectedCitation.effective_at"
              color="primary"
              variant="soft"
              :label="`生效：${selectedCitation.effective_at}`"
            />
          </div>
          <div>
            <p class="text-xs font-medium text-muted">
              原文位置
            </p>
            <p class="mt-1 text-sm text-highlighted">
              {{ selectedCitation.doc_id }} · {{ selectedCitation.locator }}
            </p>
          </div>
          <blockquote class="rounded-lg border-l-4 border-primary bg-elevated p-4 text-sm leading-7 text-highlighted">
            {{ selectedCitation.excerpt }}
          </blockquote>
          <div class="grid gap-3 text-xs text-muted sm:grid-cols-2">
            <div><span class="block">来源级别</span><strong class="mt-1 block text-highlighted">{{ selectedCitation.authority }}</strong></div>
            <div>
              <span class="block">内容校验</span><strong
                class="mt-1 block truncate font-mono text-highlighted"
                :title="selectedCitation.content_hash"
              >{{ selectedCitation.content_hash.slice(0, 16) }}…</strong>
            </div>
          </div>
        </div>
      </template>
    </UModal>
  </div>
</template>
