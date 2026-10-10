<script setup lang="ts">
import { computed, ref } from 'vue'
import { $fetch } from 'ofetch'

interface CatalogDocument {
  doc_id: string
  title: string
  source_type: string
}

const selectedDocumentIds = defineModel<string[]>({ default: () => [] })
const documents = ref<CatalogDocument[]>([])
const filter = ref('')
const expanded = ref(false)
const loading = ref(false)
const loadError = ref('')

const filteredDocuments = computed(() => {
  const term = filter.value.trim().toLocaleLowerCase()
  if (!term) return documents.value
  return documents.value.filter(document =>
    `${document.title} ${document.doc_id}`.toLocaleLowerCase().includes(term),
  )
})

async function togglePicker() {
  expanded.value = !expanded.value
  if (!expanded.value || documents.value.length || loading.value) return
  loading.value = true
  loadError.value = ''
  try {
    documents.value = await $fetch<CatalogDocument[]>('/api/research/documents')
  } catch {
    loadError.value = 'Unable to load knowledge base documents. Close and reopen the picker to retry.'
  } finally {
    loading.value = false
  }
}

function toggleDocument(docId: string) {
  selectedDocumentIds.value = selectedDocumentIds.value.includes(docId)
    ? selectedDocumentIds.value.filter(id => id !== docId)
    : [...selectedDocumentIds.value, docId]
}
</script>

<template>
  <div class="research-mode-notice">
    <div class="flex min-w-0 items-start gap-3">
      <span class="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
        <UIcon name="i-lucide-telescope" class="size-4" />
      </span>
      <div class="min-w-0 flex-1">
        <p class="text-sm font-semibold text-highlighted">Deep Research enabled</p>
        <p class="mt-0.5 text-xs leading-5 text-muted">
          Choose knowledge base documents to freeze the source scope. Review and approve the plan before research starts.
        </p>
        <button
          type="button"
          class="mt-3 inline-flex min-h-9 items-center gap-2 rounded-lg border border-default bg-default px-3 text-xs font-medium text-highlighted transition-colors hover:bg-elevated focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          :aria-expanded="expanded"
          @click="togglePicker"
        >
          <UIcon name="i-lucide-files" class="size-4 text-muted" />
          {{ selectedDocumentIds.length ? `${selectedDocumentIds.length} documents selected` : 'Select knowledge base documents' }}
          <UIcon :name="expanded ? 'i-lucide-chevron-up' : 'i-lucide-chevron-down'" class="size-3.5 text-muted" />
        </button>
      </div>
    </div>

    <div v-if="expanded" class="mt-3 border-t border-default pt-3 sm:ml-11">
      <label class="sr-only" for="research-source-filter">Filter knowledge base documents</label>
      <input
        id="research-source-filter"
        v-model="filter"
        type="search"
        placeholder="Filter by file name…"
        class="h-9 w-full rounded-lg border border-default bg-default px-3 text-sm text-highlighted outline-none placeholder:text-dimmed focus:border-primary"
      >
      <p v-if="loading" class="py-5 text-center text-xs text-muted">Loading knowledge base documents…</p>
      <p v-else-if="loadError" class="py-4 text-xs text-error" role="alert">{{ loadError }}</p>
      <div v-else class="mt-2 max-h-56 overflow-y-auto rounded-lg border border-default bg-default p-1">
        <button
          v-for="document in filteredDocuments"
          :key="document.doc_id"
          :aria-pressed="selectedDocumentIds.includes(document.doc_id)"
          type="button"
          class="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm hover:bg-elevated focus-visible:outline-2 focus-visible:outline-primary"
          @click="toggleDocument(document.doc_id)"
        >
          <UIcon
            :name="selectedDocumentIds.includes(document.doc_id) ? 'i-lucide-square-check-big' : 'i-lucide-square'"
            :class="selectedDocumentIds.includes(document.doc_id) ? 'text-primary' : 'text-dimmed'"
            class="size-4 shrink-0"
          />
          <span class="min-w-0 flex-1 truncate text-highlighted">{{ document.title }}</span>
        </button>
        <p v-if="!filteredDocuments.length" class="px-3 py-5 text-center text-xs text-muted">
          No matching documents
        </p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.research-mode-notice {
  margin-top: 0.625rem;
  border: 1px solid color-mix(in srgb, var(--ui-primary) 24%, var(--ui-border));
  border-radius: 0.875rem;
  background: color-mix(in srgb, var(--ui-primary) 5%, var(--ui-bg));
  padding: 0.875rem;
}
</style>
