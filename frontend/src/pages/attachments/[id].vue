<script setup lang="ts">
import { computed } from 'vue'
import { $fetch } from 'ofetch'
import { useRoute } from 'vue-router'

const route = useRoute('/attachments/[id]')
const attachmentId = String(route.params.id)
const evidenceId = String(route.query.evidence_id || '')
const requestedVersion = Number(route.query.version || 0)
const [metadata, evidenceResponse, revisionResponse] = await Promise.all([
  $fetch<any>(`/api/attachments/${attachmentId}`),
  $fetch<any>(`/api/attachments/${attachmentId}/evidence`),
  evidenceId
    ? $fetch<any>(`/api/attachments/${attachmentId}/evidence/${evidenceId}/revisions`).catch(() => ({ items: [] }))
    : Promise.resolve({ items: [] }),
])
const items = Array.isArray(evidenceResponse.items) ? evidenceResponse.items : []
const revisions = Array.isArray(revisionResponse.items) ? revisionResponse.items : []
const evidence = computed(() => items.find((item: any) => item.evidence_id === evidenceId) || items[0] || null)
const citedContent = computed(() => {
  if (!evidence.value || !requestedVersion || requestedVersion === evidence.value.version) return evidence.value?.content || ''
  const leavingRevision = revisions.find((item: any) => Number(item.from_version) === requestedVersion)
  if (leavingRevision) return leavingRevision.previous_content
  const arrivingRevision = revisions.find((item: any) => Number(item.to_version) === requestedVersion)
  return arrivingRevision?.corrected_content || evidence.value.original_content || ''
})
const locator = computed(() => evidence.value?.locator || {})
const previewUrl = computed(() => {
  const page = Number(locator.value.page || locator.value.slide || 0)
  return `/api/attachments/${attachmentId}/preview${page ? `?page=${page}` : ''}`
})
const canPreviewImage = computed(() => {
  const extension = String(metadata.extension || '').toLowerCase()
  const hasPreview = Array.isArray(metadata.previews) && metadata.previews.length > 0
  return !!locator.value.bbox
    || extension === '.pdf'
    || ['.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'].includes(extension)
    || (hasPreview && ['.doc', '.docx', '.ppt', '.pptx'].includes(extension))
})
const boxStyle = computed(() => {
  const box = locator.value.bbox
  if (!Array.isArray(box) || box.length !== 4) return {}
  return {
    left: `${box[0] * 100}%`, top: `${box[1] * 100}%`,
    width: `${(box[2] - box[0]) * 100}%`, height: `${(box[3] - box[1]) * 100}%`,
  }
})
</script>

<template>
  <main class="mx-auto max-w-5xl p-6 space-y-5">
    <header class="flex items-start justify-between gap-4">
      <div><h1 class="text-xl font-semibold">{{ metadata.filename }}</h1><p class="text-sm text-muted">Attachment Evidence Locator · {{ evidence?.source_type || 'No Evidence' }}</p></div>
      <a :href="`/api/attachments/${attachmentId}/content`" class="text-primary underline">Download Original</a>
    </header>
    <div v-if="requestedVersion && evidence && requestedVersion !== evidence.version" class="rounded border border-warning p-3 text-sm text-warning">
      This answer cited Evidence v{{ requestedVersion }}; current latest version is v{{ evidence.version }}. Displaying the historical version used when generating the answer.
    </div>
    <section class="grid gap-4 md:grid-cols-2">
      <div v-if="canPreviewImage" class="relative self-start overflow-hidden rounded border border-default bg-elevated">
        <img :src="previewUrl" class="block w-full" alt="Attachment evidence page preview">
        <span v-if="locator.bbox" class="pointer-events-none absolute border-2 border-red-500 bg-red-500/10" :style="boxStyle" />
      </div>
      <div class="space-y-3">
        <div class="rounded border border-default p-3 text-sm">
          <div v-if="locator.page">Page: {{ locator.page }}</div>
          <div v-if="locator.slide">Slide: {{ locator.slide }}</div>
          <div v-if="locator.sheet">Sheet: {{ locator.sheet }}</div>
          <div v-if="locator.cell_range">Cell: {{ locator.cell_range }}</div>
          <div v-if="locator.bbox">Region: {{ locator.bbox.join(', ') }}</div>
          <div>Evidence: {{ evidence?.evidence_id || '—' }} · v{{ evidence?.version || '—' }} · Confidence {{ evidence?.confidence ?? '—' }}</div>
        </div>
        <div class="rounded border border-default p-3">
          <div class="mb-2 text-xs text-muted">{{ requestedVersion && requestedVersion !== evidence?.version ? `Cited Content (v${requestedVersion})` : 'Current Content' }}</div>
          <pre class="whitespace-pre-wrap break-words text-sm">{{ citedContent || 'No evidence to display' }}</pre>
        </div>
        <details v-if="evidence?.original_content && evidence.original_content !== evidence.content" class="rounded border border-default p-3">
          <summary class="cursor-pointer text-sm">View original recognition results</summary>
          <pre class="mt-2 whitespace-pre-wrap break-words text-sm">{{ evidence.original_content }}</pre>
        </details>
      </div>
    </section>
  </main>
</template>
