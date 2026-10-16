<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { $fetch, ofetch } from 'ofetch'
import type { ChunkCitation } from './tool/Sources.vue'
import ChatComark from './Comark'
import { evidenceUrl, evidenceError } from '../../utils/evidence'
import { locateEvidenceExcerpt, stripConfluenceLocalIds } from '../../../shared/evidenceExcerpt'

const props = defineProps<{ open: boolean, doc: ChunkCitation | null, allCitations?: ChunkCitation[], messageId?: string, researchId?: string }>()
const emit = defineEmits<{ 'update:open': [value: boolean] }>()
const loading = ref(false)
const error = ref<string | null>(null)
const evidence = ref<ChunkCitation | null>(null)
const source = ref<{ doc_id?: string, title?: string, content?: string, source_url?: string, image_url?: string } | null>(null)
const locatedExcerpt = ref<HTMLElement | null>(null)
let requestRevision = 0
const excerpt = computed(() => evidence.value?.excerpt || evidence.value?.chunk_text || evidence.value?.snippet || '')
const version = computed(() => evidence.value?.source_version ?? evidence.value?.version)
const sourceUrl = computed(() => {
  const url = source.value?.source_url || evidence.value?.source_url || ''
  return /^https:\/\//.test(url) ? url : ''
})
const locator = computed(() => evidence.value?.locator ? JSON.stringify(evidence.value.locator) : '')
const readableSource = computed(() => stripConfluenceLocalIds(source.value?.content || ''))
const excerptRange = computed(() => locateEvidenceExcerpt(source.value?.content || '', evidence.value?.anchor_excerpt || excerpt.value))
const exactLocation = computed(() => excerptRange.value !== null)
const sourceSegments = computed(() => {
  const text = readableSource.value
  const range = excerptRange.value
  return range ? { before: text.slice(0, range.start), excerpt: text.slice(range.start, range.end), after: text.slice(range.end) } : null
})
async function jumpToExcerpt() {
  await nextTick()
  locatedExcerpt.value?.scrollIntoView?.({ block: 'center', behavior: 'instant' })
  locatedExcerpt.value?.focus({ preventScroll: true })
}

async function loadFullDocument() {
  const revision = ++requestRevision
  loading.value = true
  error.value = null
  evidence.value = null
  source.value = null
  try {
    if (!props.doc) throw new Error('No citation selected.')
    if (props.researchId) {
      const content = await ofetch<string, 'text'>(`/api/research/jobs/${encodeURIComponent(props.researchId)}/documents/${encodeURIComponent(props.doc.doc_id)}/source`, { responseType: 'text' })
      if (revision !== requestRevision) return
      evidence.value = props.doc
      source.value = { doc_id: props.doc.doc_id, title: props.doc.title, content }
    } else if (props.messageId) {
      const result = await $fetch<{ evidence: ChunkCitation, source?: typeof source.value }>(evidenceUrl(props.messageId, props.doc.evidence_ref || ''))
      if (revision !== requestRevision) return
      evidence.value = result.evidence
      source.value = result.source ?? null
    } else {
      if (!props.doc.doc_id) throw new Error('The source document ID is missing.')
      const result = await $fetch<NonNullable<typeof source.value>>(`/api/documents/${encodeURIComponent(props.doc.doc_id)}`)
      if (revision !== requestRevision) return
      source.value = result
    }
  } catch (failure) {
    if (revision === requestRevision) error.value = evidenceError(failure)
  } finally {
    if (revision === requestRevision) loading.value = false
  }
}
watch(() => [props.open, props.doc, props.messageId, props.researchId], () => {
  if (props.open && props.doc) void loadFullDocument()
  else { requestRevision++; evidence.value = null; source.value = null; error.value = null; loading.value = false }
}, { immediate: true })
</script>

<template>
  <UModal :open="open" title="Verify answer sources" description="Inspect the authorized source text and version used for this answer" :ui="{ content: 'sm:max-w-5xl w-[92vw]' }" @update:open="emit('update:open', $event)">
    <template #content>
      <div class="flex max-h-[85vh] flex-col rounded-xl border border-default bg-default text-default">
        <header class="flex items-center justify-between gap-4 border-b border-default px-5 py-4">
          <h2 class="min-w-0 break-words font-semibold">{{ evidence?.title || source?.title || 'Verify answer sources' }}</h2>
          <UButton color="neutral" variant="ghost" icon="i-lucide-x" aria-label="Close source viewer" @click="emit('update:open', false)" />
        </header>
        <div class="min-h-48 overflow-y-auto px-5 py-4" :aria-busy="loading">
          <p v-if="loading" role="status" aria-live="polite">Verifying access and loading the source…</p>
          <div v-else-if="error" role="alert" class="space-y-3">
            <p>{{ error }}</p>
            <UButton color="neutral" variant="outline" @click="loadFullDocument">Verify again</UButton>
          </div>
          <div v-else class="space-y-4">
            <dl v-if="evidence" class="grid gap-2 text-sm">
              <div><dt class="inline text-muted">Source version used: </dt><dd class="inline">{{ version ?? 'Unknown (source version unavailable)' }}</dd></div>
              <div><dt class="inline text-muted">Locator: </dt><dd class="inline break-all">{{ locator || 'Unknown; the excerpt has no verified exact location' }}</dd></div>
              <div><dt class="inline text-muted">Content hash: </dt><dd class="inline break-all font-mono">{{ evidence.normalized_content_hash || evidence.content_hash || 'Unknown' }}</dd></div>
            </dl>
            <section v-if="excerpt" class="rounded-lg border border-default bg-elevated/40 p-4">
              <h3 class="mb-2 text-sm font-semibold">Source excerpt used for this answer</h3>
              <ChatComark :markdown="excerpt" />
            </section>
            <p v-if="evidence && !excerpt" role="status">The evidence has no excerpt. Ask again to obtain verifiable sources.</p>
            <img v-if="source?.image_url?.startsWith('/api/attachments/')" :src="source.image_url" alt="Original source image" class="max-w-full rounded-md" />
            <section v-if="source?.content" class="space-y-2">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <h3 class="text-sm font-semibold">Authorized source text</h3>
                <UButton v-if="exactLocation" color="neutral" variant="outline" size="sm" @click="jumpToExcerpt">Jump to source excerpt</UButton>
              </div>
              <p v-if="evidence && !exactLocation" role="status" class="text-sm text-muted">The excerpt could not be located exactly in the returned text. The authorized source is shown below without a location highlight.</p>
              <div v-if="sourceSegments" class="whitespace-pre-wrap break-words font-mono text-sm">
                <span>{{ sourceSegments.before }}</span><mark ref="locatedExcerpt" tabindex="-1" class="rounded bg-primary/20 text-default outline-offset-4 focus-visible:outline-2 focus-visible:outline-primary">{{ sourceSegments.excerpt }}</mark><span>{{ sourceSegments.after }}</span>
              </div>
              <ChatComark v-else :markdown="readableSource" />
            </section>
            <p v-else-if="excerpt" class="text-sm text-muted">Only the excerpt used for this answer is available. The full document and latest source version have not been verified.</p>
            <a v-if="sourceUrl" :href="sourceUrl" target="_blank" rel="noopener noreferrer" class="inline-block rounded text-primary underline focus-visible:outline-2 focus-visible:outline-primary">Open current source page (may differ from the answer version)</a>
          </div>
        </div>
        <footer class="flex justify-end border-t border-default px-5 py-3">
          <UButton color="neutral" @click="emit('update:open', false)">Close</UButton>
        </footer>
      </div>
    </template>
  </UModal>
</template>
