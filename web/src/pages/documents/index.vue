<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { $fetch } from 'ofetch'
import { useCsrf } from '../../composables/useCsrf'
import ModalConfirm from '../../components/ModalConfirm.vue'
import ModalDocumentViewer from '../../components/chat/ModalDocumentViewer.vue'

interface DocItem {
  docId: string
  title: string
  fileName: string
  fileType: string
  chunkCount: number
  charCount: number
  lastUpdated: string
  sourceUrl: string
  status?: 'processing' | 'ready' | 'error'
}

const { csrf, headerName } = useCsrf()
const toast = useToast()

const documents = ref<DocItem[]>([])
const loading = ref(true)
const searchQuery = ref('')
const selectedDocIds = ref<Set<string>>(new Set())

// Action states
const isReindexing = ref(false)
const isUploading = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)

// Delete Modal State
const showDeleteModal = ref(false)
const targetDocsToDelete = ref<string[]>([])
const isDeleting = ref(false)

// Viewer Modal State
const showViewerModal = ref(false)
const viewerDocId = ref<string | null>(null)

async function fetchDocuments() {
  loading.value = true
  try {
    const res = await $fetch<DocItem[]>('/api/documents')
    documents.value = (res || []).map(d => ({ ...d, status: d.status || 'ready' }))
  } catch (err: any) {
    toast.add({
      title: 'Failed to load documents',
      description: err.message || 'Error fetching document list',
      color: 'error'
    })
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchDocuments()
})

const filteredDocuments = computed(() => {
  if (!searchQuery.value.trim()) return documents.value
  const q = searchQuery.value.toLowerCase().trim()
  return documents.value.filter(doc =>
    doc.title.toLowerCase().includes(q) ||
    doc.fileName.toLowerCase().includes(q) ||
    doc.docId.toLowerCase().includes(q) ||
    doc.fileType.toLowerCase().includes(q)
  )
})

const totalChunks = computed(() => {
  return documents.value.reduce((acc, d) => acc + (d.chunkCount || 0), 0)
})

// Checkbox Selection
const isAllSelected = computed(() => {
  return filteredDocuments.value.length > 0 &&
    filteredDocuments.value.every(d => selectedDocIds.value.has(d.docId))
})

function toggleSelectAll() {
  if (isAllSelected.value) {
    selectedDocIds.value.clear()
  } else {
    filteredDocuments.value.forEach(d => selectedDocIds.value.add(d.docId))
  }
  selectedDocIds.value = new Set(selectedDocIds.value)
}

function toggleSelectDoc(docId: string) {
  if (selectedDocIds.value.has(docId)) {
    selectedDocIds.value.delete(docId)
  } else {
    selectedDocIds.value.add(docId)
  }
  selectedDocIds.value = new Set(selectedDocIds.value)
}

// Single Delete Trigger
function confirmDeleteSingle(docId: string) {
  targetDocsToDelete.value = [docId]
  showDeleteModal.value = true
}

// Batch Delete Trigger
function confirmDeleteSelected() {
  if (!selectedDocIds.value.size) return
  targetDocsToDelete.value = Array.from(selectedDocIds.value)
  showDeleteModal.value = true
}

// Perform Deletion
async function executeDelete() {
  if (!targetDocsToDelete.value.length) return
  isDeleting.value = true
  try {
    await $fetch('/api/documents/delete', {
      method: 'POST',
      headers: { [headerName]: csrf() },
      body: { docIds: targetDocsToDelete.value }
    })

    toast.add({
      title: 'Documents Deleted',
      description: `Successfully deleted ${targetDocsToDelete.value.length} document(s) and cleared vector indices.`,
      color: 'success'
    })

    selectedDocIds.value.clear()
    showDeleteModal.value = false
    await fetchDocuments()
  } catch (err: any) {
    toast.add({
      title: 'Deletion Failed',
      description: err.message || 'Failed to delete documents',
      color: 'error'
    })
  } finally {
    isDeleting.value = false
  }
}

// Re-index / Update Store Trigger
async function handleReindex() {
  isReindexing.value = true
  try {
    toast.add({
      title: 'Re-indexing Started',
      description: 'Scanning raw directory and updating Milvus vector store...',
      color: 'info'
    })

    const res = await $fetch<{ success: boolean; message: string }>('/api/documents/reindex', {
      method: 'POST',
      headers: { [headerName]: csrf() }
    })

    if (res.success) {
      toast.add({
        title: 'Store Updated',
        description: res.message,
        color: 'success'
      })
      await fetchDocuments()
    } else {
      toast.add({
        title: 'Re-index Warning',
        description: res.message,
        color: 'warning'
      })
    }
  } catch (err: any) {
    toast.add({
      title: 'Re-indexing Failed',
      description: err.message || 'Error executing re-indexing pipeline',
      color: 'error'
    })
  } finally {
    isReindexing.value = false
  }
}

// File Upload Trigger
function triggerUpload() {
  fileInputRef.value?.click()
}

async function handleFileChange(event: Event) {
  const files = (event.target as HTMLInputElement).files
  if (!files || !files.length) return

  isUploading.value = true
  const formData = new FormData()

  // Create optimistic pending document items (Gray text + Spinning loader)
  const pendingDocs: DocItem[] = []
  for (let i = 0; i < files.length; i++) {
    const file = files[i]
    formData.append('files', file)

    const pendingItem: DocItem = {
      docId: `proc_${Date.now()}_${i}`,
      title: file.name,
      fileName: file.name,
      fileType: file.name.split('.').pop()?.toUpperCase() || 'FILE',
      chunkCount: 0,
      charCount: file.size,
      lastUpdated: new Date().toISOString(),
      sourceUrl: file.name,
      status: 'processing'
    }
    pendingDocs.push(pendingItem)
  }

  // Prepend pending documents to list immediately
  documents.value = [...pendingDocs, ...documents.value]

  try {
    toast.add({
      title: 'Uploading Documents',
      description: `Saving to raw/ store and running data pipeline ingestion...`,
      color: 'info'
    })

    const res = await $fetch<{ success: boolean; message: string }>('/api/documents/upload', {
      method: 'POST',
      headers: { [headerName]: csrf() },
      body: formData
    })

    toast.add({
      title: 'Upload & Ingestion Complete',
      description: res.message,
      color: 'success'
    })

    if (fileInputRef.value) fileInputRef.value.value = ''
    await fetchDocuments()
  } catch (err: any) {
    toast.add({
      title: 'Upload Failed',
      description: err.message || 'Failed to upload and ingest documents',
      color: 'error'
    })
    await fetchDocuments()
  } finally {
    isUploading.value = false
  }
}

// View Document Detail
function openViewer(docId: string) {
  viewerDocId.value = docId
  showViewerModal.value = true
}

function getFileIcon(type: string) {
  const t = type.toUpperCase()
  if (t === 'PDF') return 'i-lucide-file-text text-rose-400'
  if (t === 'DOC' || t === 'DOCX') return 'i-lucide-file-type text-sky-400'
  if (t === 'JSON') return 'i-lucide-file-json text-amber-400'
  if (t === 'TXT' || t === 'MD') return 'i-lucide-file-code text-emerald-400'
  return 'i-lucide-file text-zinc-400'
}
</script>

<template>
  <div class="flex-1 flex flex-col h-full bg-zinc-950 text-zinc-100 overflow-hidden font-sans">
    
    <!-- Hidden File Input for Upload -->
    <input
      ref="fileInputRef"
      type="file"
      multiple
      accept=".pdf,.doc,.docx,.txt,.md,.json"
      class="hidden"
      @change="handleFileChange"
    />

    <!-- Header Section -->
    <header class="p-6 pb-4 border-b border-zinc-800/80 bg-zinc-900/40 shrink-0 flex flex-col md:flex-row md:items-center md:justify-between gap-4">
      <div>
        <div class="flex items-center gap-2.5">
          <div class="p-2 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
            <UIcon name="i-lucide-folder-open" class="w-6 h-6" />
          </div>
          <div>
            <h1 class="text-xl font-bold text-zinc-100 tracking-tight">Document Management</h1>
            <p class="text-xs text-zinc-400 mt-0.5">View, manage, delete, and upload knowledge base documents.</p>
          </div>
        </div>
      </div>

      <!-- Action Buttons Bar -->
      <div class="flex items-center gap-2.5 shrink-0">
        <UButton
          color="neutral"
          variant="outline"
          size="sm"
          icon="i-lucide-refresh-cw"
          label="Update Store"
          :loading="isReindexing"
          class="rounded-xl cursor-pointer font-medium"
          @click="handleReindex"
        />
        <UButton
          color="primary"
          variant="solid"
          size="sm"
          icon="i-lucide-upload"
          label="Upload Documents"
          :loading="isUploading"
          class="rounded-xl cursor-pointer font-medium px-4"
          @click="triggerUpload"
        />
      </div>
    </header>

    <!-- Overview Bar & Search Filter -->
    <div class="p-6 py-4 border-b border-zinc-800/80 bg-zinc-900/20 flex flex-col sm:flex-row items-center justify-between gap-4 shrink-0">
      
      <!-- Metrics overview chips -->
      <div class="flex flex-wrap items-center gap-3 w-full sm:w-auto">
        <div class="px-3.5 py-1.5 rounded-xl bg-zinc-900 border border-zinc-800 flex items-center gap-2 text-xs">
          <span class="text-zinc-400">Documents:</span>
          <span class="font-bold font-mono text-emerald-400">{{ documents.length }}</span>
        </div>
        <div class="px-3.5 py-1.5 rounded-xl bg-zinc-900 border border-zinc-800 flex items-center gap-2 text-xs">
          <span class="text-zinc-400">Total Chunks:</span>
          <span class="font-bold font-mono text-sky-400">{{ totalChunks.toLocaleString() }}</span>
        </div>
        <div class="px-3.5 py-1.5 rounded-xl bg-zinc-900 border border-zinc-800 flex items-center gap-2 text-xs">
          <span class="text-zinc-400">Model:</span>
          <span class="font-bold font-mono text-zinc-300">BAAI/bge-small-en-v1.5</span>
        </div>
      </div>

      <!-- Search Input -->
      <div class="w-full sm:w-72 relative">
        <UIcon name="i-lucide-search" class="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
        <input
          v-model="searchQuery"
          type="text"
          placeholder="Search documents by title..."
          class="w-full bg-zinc-900 border border-zinc-800 rounded-xl pl-9 pr-3.5 py-1.5 text-xs text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
        />
      </div>
    </div>

    <!-- Batch Selection Action Bar (Shown when items are selected) -->
    <div
      v-if="selectedDocIds.size > 0"
      class="px-6 py-2.5 bg-emerald-500/10 border-b border-emerald-500/20 flex items-center justify-between animate-in fade-in shrink-0"
    >
      <div class="flex items-center gap-2 text-xs font-semibold text-emerald-300">
        <UIcon name="i-lucide-check-circle-2" class="w-4 h-4 text-emerald-400" />
        <span>Selected {{ selectedDocIds.size }} document(s)</span>
      </div>
      <div class="flex items-center gap-2">
        <UButton
          color="neutral"
          variant="ghost"
          size="xs"
          label="Clear Selection"
          class="rounded-lg text-zinc-400 hover:text-white"
          @click="selectedDocIds.clear()"
        />
        <UButton
          color="error"
          variant="solid"
          size="xs"
          icon="i-lucide-trash-2"
          :label="`Delete Selected (${selectedDocIds.size})`"
          class="rounded-lg font-medium px-3"
          @click="confirmDeleteSelected"
        />
      </div>
    </div>

    <!-- Document Table List -->
    <div class="flex-1 overflow-y-auto p-6">
      
      <!-- Loading State -->
      <div v-if="loading && documents.length === 0" class="flex flex-col items-center justify-center py-24 text-zinc-500 space-y-3">
        <UIcon name="i-lucide-loader-2" class="w-8 h-8 animate-spin text-emerald-400" />
        <p class="text-xs">Loading ingested documents...</p>
      </div>

      <!-- Empty State -->
      <div v-else-if="filteredDocuments.length === 0" class="flex flex-col items-center justify-center py-24 text-zinc-500 space-y-3 bg-zinc-900/30 rounded-3xl border border-zinc-800/80">
        <UIcon name="i-lucide-file-x-2" class="w-12 h-12 text-zinc-600" />
        <p class="text-sm font-semibold text-zinc-300">No documents found</p>
        <p class="text-xs text-zinc-500 max-w-sm text-center">
          Upload documents or click "Update Store" to ingest raw files into Milvus.
        </p>
        <UButton
          color="primary"
          size="xs"
          icon="i-lucide-upload"
          label="Upload Now"
          class="rounded-xl mt-2 cursor-pointer"
          @click="triggerUpload"
        />
      </div>

      <!-- Data Table -->
      <div v-else class="bg-zinc-900/40 rounded-2xl border border-zinc-800/80 overflow-hidden shadow-xs">
        <table class="w-full text-left text-xs text-zinc-300 border-collapse">
          
          <!-- Table Header -->
          <thead class="bg-zinc-900/80 text-zinc-400 font-semibold border-b border-zinc-800">
            <tr>
              <th class="py-3 px-4 w-10">
                <input
                  type="checkbox"
                  :checked="isAllSelected"
                  class="rounded accent-emerald-500 bg-zinc-950 border-zinc-700 cursor-pointer"
                  @change="toggleSelectAll"
                />
              </th>
              <th class="py-3 px-4">Document Title / File Name</th>
              <th class="py-3 px-4 hidden md:table-cell">Doc ID</th>
              <th class="py-3 px-4 text-center">Chunks</th>
              <th class="py-3 px-4 text-right hidden sm:table-cell">Size</th>
              <th class="py-3 px-4 text-right hidden lg:table-cell">Last Updated</th>
              <th class="py-3 px-4 text-right pr-6">Actions</th>
            </tr>
          </thead>

          <!-- Table Body -->
          <tbody class="divide-y divide-zinc-800/60">
            <tr
              v-for="doc in filteredDocuments"
              :key="doc.docId"
              :class="[
                'hover:bg-zinc-800/40 transition-colors group',
                selectedDocIds.has(doc.docId) ? 'bg-emerald-500/5' : '',
                doc.status === 'processing' ? 'bg-zinc-900/60' : ''
              ]"
            >
              <!-- Selection Checkbox -->
              <td class="py-3.5 px-4">
                <input
                  type="checkbox"
                  :disabled="doc.status === 'processing'"
                  :checked="selectedDocIds.has(doc.docId)"
                  class="rounded accent-emerald-500 bg-zinc-950 border-zinc-700 cursor-pointer disabled:opacity-40"
                  @change="toggleSelectDoc(doc.docId)"
                />
              </td>

              <!-- Document Title & Format Badge -->
              <td class="py-3.5 px-4 font-medium">
                <div class="flex items-center gap-2.5">
                  <UIcon :name="getFileIcon(doc.fileType)" class="w-4 h-4 shrink-0" />
                  
                  <!-- Title text: Gray & Italic when processing, White & Bold when ready -->
                  <span
                    :class="[
                      'truncate max-w-xs sm:max-w-md font-semibold transition-colors',
                      doc.status === 'processing' ? 'text-zinc-500 italic opacity-75' : 'text-zinc-100'
                    ]"
                    :title="doc.title"
                  >
                    {{ doc.title }}
                  </span>

                  <!-- Spinning Loader Indicator when processing -->
                  <div v-if="doc.status === 'processing'" class="flex items-center gap-1.5 text-[11px] text-sky-400 font-mono">
                    <UIcon name="i-lucide-loader-2" class="w-4 h-4 animate-spin shrink-0" />
                    <span class="text-[10px] opacity-80">Processing...</span>
                  </div>

                  <span class="px-2 py-0.5 text-[10px] font-mono font-bold rounded bg-zinc-800 border border-zinc-700/80 text-zinc-300">
                    {{ doc.fileType }}
                  </span>
                </div>
              </td>

              <!-- Doc ID -->
              <td class="py-3.5 px-4 font-mono text-[11px] text-zinc-500 hidden md:table-cell truncate max-w-[140px]" :title="doc.docId">
                {{ doc.docId }}
              </td>

              <!-- Chunk Count Badge -->
              <td class="py-3.5 px-4 text-center">
                <span v-if="doc.status === 'processing'" class="px-2.5 py-1 text-[11px] font-mono rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20 inline-flex items-center gap-1.5">
                  <UIcon name="i-lucide-loader-2" class="w-3 h-3 animate-spin" /> Ingesting...
                </span>
                <span v-else class="px-2.5 py-1 text-[11px] font-mono font-bold rounded-full bg-sky-500/10 text-sky-400 border border-sky-500/20">
                  {{ doc.chunkCount }} chunks
                </span>
              </td>

              <!-- Size -->
              <td class="py-3.5 px-4 text-right font-mono text-zinc-400 hidden sm:table-cell">
                {{ (doc.charCount / 1024).toFixed(1) }} KB
              </td>

              <!-- Last Updated Date -->
              <td class="py-3.5 px-4 text-right text-zinc-500 hidden lg:table-cell">
                {{ new Date(doc.lastUpdated).toLocaleDateString() }}
              </td>

              <!-- Actions Column -->
              <td class="py-3.5 px-4 text-right pr-6">
                <div class="flex items-center justify-end gap-1">
                  <!-- View Details -->
                  <UButton
                    :disabled="doc.status === 'processing'"
                    color="neutral"
                    variant="ghost"
                    size="xs"
                    icon="i-lucide-eye"
                    class="rounded-lg text-zinc-400 hover:text-white disabled:opacity-30"
                    title="View Document Chunks"
                    @click="openViewer(doc.docId)"
                  />
                  <!-- Delete Single -->
                  <UButton
                    :disabled="doc.status === 'processing'"
                    color="error"
                    variant="ghost"
                    size="xs"
                    icon="i-lucide-trash-2"
                    class="rounded-lg text-zinc-400 hover:text-red-400 disabled:opacity-30"
                    title="Delete Document"
                    @click="confirmDeleteSingle(doc.docId)"
                  />
                </div>
              </td>
            </tr>
          </tbody>

        </table>
      </div>

    </div>

    <!-- Modals -->

    <!-- Delete Confirmation Modal -->
    <ModalConfirm
      v-if="showDeleteModal"
      v-model:open="showDeleteModal"
      title="Delete Document(s)"
      :description="`Are you sure you want to delete ${targetDocsToDelete.length} document(s)? This will permanently remove all text chunks and vector embeddings from Milvus.`"
      confirm-text="Delete Permanently"
      confirm-color="error"
      :loading="isDeleting"
      @confirm="executeDelete"
    />

    <!-- Document Content Viewer Modal -->
    <ModalDocumentViewer
      v-if="showViewerModal"
      v-model:open="showViewerModal"
      :doc-id="viewerDocId"
    />

  </div>
</template>
