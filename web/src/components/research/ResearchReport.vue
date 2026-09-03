<script setup lang="ts">
import type { ResearchJob, ResearchReport } from '../../types/research'
import ChatComark from '../chat/Comark'

const props = defineProps<{ job: ResearchJob, report: ResearchReport }>()
const emit = defineEmits<{ restart: [] }>()

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
              {{ report.result_status === 'complete' ? '研究完成' : '研究完成 · 资料存在限制' }}
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
      <div class="mt-5 flex flex-wrap gap-2">
        <UBadge
          color="neutral"
          variant="soft"
          :label="`${report.claim_ids.length} 个结论`"
        /><UBadge
          color="neutral"
          variant="soft"
          :label="`${report.evidence_ids.length} 条引用证据`"
        /><UBadge
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

    <section class="rounded-xl border border-default bg-elevated/30 p-5">
      <h3 class="font-semibold text-highlighted">
        证据索引
      </h3>
      <div class="mt-3 flex flex-wrap gap-2">
        <code
          v-for="evidenceId in report.evidence_ids"
          :key="evidenceId"
          class="rounded-md bg-default px-2 py-1 text-xs text-primary"
        >{{ evidenceId }}</code>
      </div>
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
  </div>
</template>

