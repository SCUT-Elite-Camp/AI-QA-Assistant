<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { $fetch } from 'ofetch'
import { useCsrf } from '../../composables/useCsrf'
import DocumentModal from './DocumentModal.vue'

const props = defineProps<{
  open: boolean
  topicId: string
}>()

const emit = defineEmits<{
  (e: 'update:open', val: boolean): void
}>()

const { csrf, headerName } = useCsrf()
const loading = ref(false)
const documents = ref<any[]>([])

// Document preview state
const showPreviewModal = ref(false)
const activePreviewDoc = ref<any>(null)

async function fetchDocuments() {
  if (!props.topicId) return
  loading.value = true
  try {
    const res: any = await $fetch(`/api/topics/${props.topicId}/documents`)
    documents.value = res || []
  } catch (e) {
    console.error('Failed to fetch topic documents:', e)
    documents.value = []
  } finally {
    loading.value = false
  }
}

async function removeDoc(docId: string, event: Event) {
  event.stopPropagation()
  try {
    await $fetch(`/api/topics/${props.topicId}/documents/${docId}`, {
      method: 'DELETE',
      headers: { [headerName]: csrf() }
    })
    documents.value = documents.value.filter(d => d.docId !== docId)
  } catch (e) {
    console.error('Failed to remove document:', e)
  }
}

function openDocModal(doc: any) {
  activePreviewDoc.value = doc
  showPreviewModal.value = true
}

function cleanTitle(doc: any): string {
  if (!doc) return ''
  let title = doc.title || doc.docId || ''
  // Strip UUID prefix if filename starts with hash/UUID
  title = title.replace(/^[a-f0-9]{32}_/i, '').replace(/^[a-f0-9-]{36}_/i, '')
  return title
}

watch(() => props.open, (val) => {
  if (val) fetchDocuments()
}, { immediate: true })

onMounted(() => {
  if (props.open) fetchDocuments()
})
</script>

<template>
  <UModal
    :open="open"
    :ui="{ width: 'sm:max-w-3xl' }"
    @update:open="emit('update:open', $event)"
  >
    <template #content>
      <div class="p-6 bg-zinc-950 text-zinc-100 rounded-3xl space-y-4 max-h-[80vh] overflow-y-auto border border-zinc-800">
        <!-- Header -->
        <div class="flex items-center justify-between pb-3 border-b border-zinc-800">
          <div class="flex items-center gap-2 font-semibold text-zinc-100">
            <UIcon name="i-heroicons-folder-open" class="w-5 h-5 text-emerald-400" />
            <span>Document Pool ({{ documents.length }})</span>
          </div>
          <UButton
            color="neutral"
            variant="ghost"
            icon="i-heroicons-x-mark"
            size="sm"
            class="rounded-full text-zinc-400 hover:text-white"
            @click="emit('update:open', false)"
          />
        </div>

        <!-- Body Content -->
        <div class="py-2">
          <div v-if="loading" class="text-center py-10 text-zinc-400 text-xs flex items-center justify-center gap-2">
            <UIcon name="i-heroicons-arrow-path" class="w-4 h-4 animate-spin text-emerald-500" />
            <span>Loading topic document pool...</span>
          </div>

          <div v-else-if="!documents.length" class="text-center py-12 text-xs text-zinc-400 bg-zinc-900/40 rounded-2xl border border-zinc-800/80">
            <UIcon name="i-heroicons-document-text" class="w-10 h-10 text-zinc-700 mx-auto mb-2" />
            <p>No reference documents uploaded for this topic. Uploaded files will be deduplicated and saved here.</p>
          </div>

          <!-- Sleek Horizontal Rectangular Cards List -->
          <div v-else class="grid grid-cols-1 gap-2.5">
            <div
              v-for="doc in documents"
              :key="doc.docId || doc.id"
              class="group flex items-center justify-between p-3.5 bg-zinc-900/90 hover:bg-zinc-900 border border-zinc-800 hover:border-emerald-500/50 rounded-xl cursor-pointer transition-all shadow-xs"
              @click="openDocModal(doc)"
            >
              <div class="flex items-center gap-3 min-w-0 flex-1">
                <div class="w-8 h-8 rounded-lg bg-emerald-500/10 text-emerald-400 flex items-center justify-center shrink-0">
                  <UIcon name="i-heroicons-document-text" class="w-4 h-4" />
                </div>
                <div class="min-w-0 flex-1">
                  <h4 class="font-medium text-xs text-zinc-200 group-hover:text-emerald-400 transition-colors truncate" :title="cleanTitle(doc)">
                    {{ cleanTitle(doc) }}
                  </h4>
                  <p v-if="doc.snippet || doc.content" class="text-[11px] text-zinc-400 truncate mt-0.5 font-mono">
                    {{ doc.snippet || doc.content }}
                  </p>
                </div>
              </div>

              <!-- Delete Action Button -->
              <UButton
                color="neutral"
                variant="ghost"
                size="xs"
                icon="i-heroicons-trash"
                class="text-zinc-500 hover:text-rose-400 opacity-60 group-hover:opacity-100 transition-opacity ml-3 shrink-0"
                @click="removeDoc(doc.docId, $event)"
              />
            </div>
          </div>
        </div>
      </div>
    </template>
  </UModal

  <!-- Full Content Viewer Modal -->
  <DocumentModal
    v-if="showPreviewModal && activePreviewDoc"
    v-model:open="showPreviewModal"
    :doc-id="activePreviewDoc.docId"
    :doc-title="cleanTitle(activePreviewDoc)"
    :doc-content="activePreviewDoc.content || activePreviewDoc.snippet"
  />
</template>
