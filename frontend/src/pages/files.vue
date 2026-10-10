<route lang="yaml">
meta:
  layout: admin
</route>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { $fetch } from 'ofetch'
import { useCsrf } from '../composables/useCsrf'
import { useUserSession } from '../composables/useUserSession'
import FilePermissionDialog, { type FileWithPermission } from '../components/admin/FilePermissionDialog.vue'

interface FileItem {
  id: string
  userId: string
  name: string
  originalName: string
  mimeType: string
  size: number
  visibility: 'private' | 'shared'
  canManage: boolean
  spaceKey?: string
  docId?: string
  storagePath?: string
  grants: Array<{ grantType: string; grantId: string | null }>
  createdAt: string
}

const toast = useToast()
const { csrf, headerName } = useCsrf()
const { fetchSession } = useUserSession()

const files = ref<FileItem[]>([])
const loading = ref(true)
const syncing = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)

// 搜索与空间筛选
const searchQuery = ref('')
const selectedSpace = ref('ALL')

// 预览弹窗状态
const previewOpen = ref(false)
const previewDoc = ref<FileItem | null>(null)
const previewContent = ref('')
const previewLoading = ref(false)

// 权限配置弹窗：uploadFile 非空为上传模式，permissionFile 非空为编辑模式
const uploadFile = ref<File | null>(null)
const permissionFile = ref<FileWithPermission | null>(null)

const formatSize = (bytes: number): string => {
  if (!bytes) return '0 B'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

const formatTime = (iso: string): string => {
  if (!iso) return '—'
  const d = new Date(iso)
  const pad = (n: number) => n.toString().padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const mimeIcon = (name: string, _mime?: string): string => {
  const n = (name || '').toLowerCase()
  if (n.endsWith('.pptx') || n.endsWith('.ppt')) return 'i-lucide-presentation'
  if (n.endsWith('.xlsx') || n.endsWith('.xls') || n.endsWith('.csv')) return 'i-lucide-table'
  if (n.endsWith('.pdf')) return 'i-lucide-file-text'
  if (n.endsWith('.doc') || n.endsWith('.docx')) return 'i-lucide-file-text'
  if (n.endsWith('.png') || n.endsWith('.jpg') || n.endsWith('.jpeg')) return 'i-lucide-image'
  if (n.endsWith('.md')) return 'i-lucide-file-code'
  return 'i-lucide-file-text'
}

// 统计各空间的文档数量
const spaceCounts = computed(() => {
  const counts: Record<string, number> = { ALL: files.value.length }
  for (const f of files.value) {
    const key = f.spaceKey || 'DEFAULT'
    counts[key] = (counts[key] || 0) + 1
  }
  return counts
})

const distinctSpaces = computed(() => {
  const set = new Set<string>()
  for (const f of files.value) {
    set.add(f.spaceKey || 'DEFAULT')
  }
  return Array.from(set).sort()
})

// 筛选后的文档列表
const filteredFiles = computed(() => {
  return files.value.filter(item => {
    // 空间筛选
    if (selectedSpace.value !== 'ALL' && (item.spaceKey || 'DEFAULT') !== selectedSpace.value) {
      return false
    }
    // 关键词搜索
    if (searchQuery.value.trim()) {
      const q = searchQuery.value.trim().toLowerCase()
      const matchName = (item.name || item.originalName || '').toLowerCase().includes(q)
      const matchDocId = (item.docId || '').toLowerCase().includes(q)
      const matchSpace = (item.spaceKey || '').toLowerCase().includes(q)
      if (!matchName && !matchDocId && !matchSpace) return false
    }
    return true
  })
})

async function loadFiles() {
  loading.value = true
  try {
    files.value = await $fetch<FileItem[]>('/api/files')
  } catch (err: any) {
    console.error('[loadFiles] Failed to load files:', err)
    toast.add({ title: 'Failed to load knowledge base document list', color: 'error' })
  } finally {
    loading.value = false
  }
}

async function handleSyncKnowledge() {
  syncing.value = true
  try {
    await loadFiles()
    toast.add({ title: `Synchronized ${files.value.length} knowledge base documents`, color: 'success' })
  } finally {
    syncing.value = false
  }
}

async function openPreview(item: FileItem) {
  previewDoc.value = item
  previewContent.value = ''
  previewOpen.value = true
  previewLoading.value = true
  try {
    const text = await $fetch<string>(`/api/files/${item.id}`)
    previewContent.value = typeof text === 'string' ? text : JSON.stringify(text, null, 2)
  } catch (err) {
    previewContent.value = 'Failed to load document content'
  } finally {
    previewLoading.value = false
  }
}

function handleDownload(item: FileItem) {
  window.open(`/api/files/${item.id}?download=1`, '_blank')
}

async function handleDelete(item: FileItem) {
  if (!confirm(`Are you sure you want to delete file "${item.originalName}"?`)) return
  try {
    await $fetch(`/api/files/${item.id}`, {
      method: 'DELETE',
      headers: { [headerName]: csrf() },
    })
    toast.add({ title: 'Document removed', color: 'success' })
    await loadFiles()
  } catch (err: any) {
    toast.add({ title: 'Failed to delete file', color: 'error' })
  }
}

async function handleFileSelected(fileList: FileList | null) {
  if (!fileList || fileList.length === 0) return
  const selected = fileList[0]
  if (!selected) return
  uploadFile.value = selected
  if (fileInputRef.value) fileInputRef.value.value = ''
}

function onDialogSaved() {
  uploadFile.value = null
  permissionFile.value = null
  loadFiles()
}

onMounted(async () => {
  await fetchSession().catch(() => {})
  loadFiles()
})
</script>

<template>
  <div class="space-y-6">
    <!-- Header Title & Controls -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-6 border-b border-zinc-200/80 dark:border-zinc-800/80">
      <div class="space-y-1">
        <div class="flex items-center gap-2.5">
          <h1 class="text-2xl sm:text-3xl font-bold tracking-tight text-zinc-950 dark:text-white">
            Knowledge Base & File Permissions
          </h1>
          <span class="px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
            Connected
          </span>
        </div>
        <p class="text-sm text-zinc-500 dark:text-zinc-400">
          Knowledge base documents connected. Access permissions correspond to respective <span class="font-semibold text-primary-500">Space Keys</span> with granular RBAC scoping.
        </p>
      </div>

      <div class="flex items-center gap-2.5 shrink-0">
        <input
          ref="fileInputRef"
          type="file"
          class="hidden"
          @change="handleFileSelected(($event.target as HTMLInputElement).files)"
        />
        <UButton
          icon="i-lucide-refresh-cw"
          color="neutral"
          variant="outline"
          size="sm"
          :loading="syncing || loading"
          class="rounded-xl shadow-2xs font-medium"
          @click="handleSyncKnowledge"
        >
          Sync Knowledge Base
        </UButton>
        <UButton
          icon="i-lucide-upload"
          color="primary"
          size="sm"
          class="rounded-xl shadow-xs font-semibold px-4 py-2"
          @click="fileInputRef?.click()"
        >
          Upload Document
        </UButton>
      </div>
    </div>

    <!-- Space Metrics Bar -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
      <div
        class="p-4 rounded-2xl border transition-all cursor-pointer bg-white/70 dark:bg-zinc-900/70 backdrop-blur-xl shadow-xs"
        :class="selectedSpace === 'ALL' ? 'border-primary-500 ring-2 ring-primary-500/20' : 'border-zinc-200/80 dark:border-zinc-800/80 hover:border-zinc-300 dark:hover:border-zinc-700'"
        @click="selectedSpace = 'ALL'"
      >
        <div class="flex items-center justify-between">
          <span class="text-xs font-medium text-zinc-500 dark:text-zinc-400">All Knowledge Documents</span>
          <UIcon name="i-lucide-library" class="w-4 h-4 text-primary-500" />
        </div>
        <div class="text-2xl font-bold text-zinc-950 dark:text-white mt-1">{{ files.length }}</div>
        <div class="text-xs text-zinc-400 mt-0.5">Across {{ distinctSpaces.length }} spaces</div>
      </div>

      <div
        v-for="space in distinctSpaces"
        :key="space"
        class="p-4 rounded-2xl border transition-all cursor-pointer bg-white/70 dark:bg-zinc-900/70 backdrop-blur-xl shadow-xs"
        :class="selectedSpace === space ? 'border-indigo-500 ring-2 ring-indigo-500/20' : 'border-zinc-200/80 dark:border-zinc-800/80 hover:border-zinc-300 dark:hover:border-zinc-700'"
        @click="selectedSpace = space"
      >
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-1.5">
            <span class="text-xs font-semibold text-zinc-700 dark:text-zinc-300">Space:</span>
            <UBadge color="indigo" variant="soft" size="xs">{{ space }}</UBadge>
          </div>
          <UIcon name="i-lucide-key-round" class="w-4 h-4 text-indigo-500" />
        </div>
        <div class="text-2xl font-bold text-zinc-950 dark:text-white mt-1">{{ spaceCounts[space] || 0 }}</div>
        <div class="text-xs text-zinc-400 mt-0.5">Scope: {{ space }}</div>
      </div>
    </div>

    <!-- Search & Filter Controls -->
    <div class="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
      <div class="relative flex-1 max-w-md">
        <UIcon name="i-lucide-search" class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400" />
        <input
          v-model="searchQuery"
          type="text"
          placeholder="Search document title, filename, or Doc ID..."
          class="w-full pl-9 pr-4 py-2 text-sm bg-white/80 dark:bg-zinc-900/80 border border-zinc-200/90 dark:border-zinc-800/80 rounded-xl outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 backdrop-blur-md transition-all"
        />
        <button
          v-if="searchQuery"
          type="button"
          class="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200"
          @click="searchQuery = ''"
        >
          <UIcon name="i-lucide-x" class="w-3.5 h-3.5" />
        </button>
      </div>

      <div class="flex items-center gap-2">
        <span class="text-xs text-zinc-400 hidden sm:inline">Space Filter:</span>
        <div class="flex items-center gap-1 p-1 bg-zinc-200/50 dark:bg-zinc-800/50 rounded-xl border border-zinc-300/40 dark:border-zinc-700/40 backdrop-blur-md">
          <button
            type="button"
            class="px-2.5 py-1 rounded-lg text-xs transition-all font-medium"
            :class="selectedSpace === 'ALL' ? 'bg-white dark:bg-zinc-900 text-zinc-950 dark:text-white shadow-xs font-semibold' : 'text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white'"
            @click="selectedSpace = 'ALL'"
          >
            All ({{ files.length }})
          </button>
          <button
            v-for="space in distinctSpaces"
            :key="space"
            type="button"
            class="px-2.5 py-1 rounded-lg text-xs transition-all font-medium"
            :class="selectedSpace === space ? 'bg-white dark:bg-zinc-900 text-indigo-600 dark:text-indigo-400 shadow-xs font-semibold' : 'text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white'"
            @click="selectedSpace = space"
          >
            {{ space }} ({{ spaceCounts[space] || 0 }})
          </button>
        </div>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading && !files.length" class="flex flex-col items-center justify-center py-24 gap-3">
      <UIcon name="i-lucide-loader-circle" class="size-8 animate-spin text-zinc-900 dark:text-white" />
      <p class="text-sm text-zinc-400">Loading knowledge base files...</p>
    </div>

    <!-- Empty -->
    <div v-else-if="filteredFiles.length === 0" class="text-center py-20 border border-dashed border-zinc-200 dark:border-zinc-800 rounded-2xl bg-white/50 dark:bg-zinc-900/50">
      <div class="w-12 h-12 rounded-2xl bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center mx-auto mb-3 text-zinc-400">
        <UIcon name="i-lucide-folder-open" class="size-6" />
      </div>
      <p class="font-medium text-zinc-900 dark:text-zinc-100">No matching documents found</p>
      <p class="text-sm text-zinc-500 mt-1">Try adjusting search keyword or selecting a different space filter.</p>
    </div>

    <!-- Files Table -->
    <div v-else class="rounded-2xl bg-white/80 dark:bg-zinc-900/80 border border-zinc-200/90 dark:border-zinc-800/80 backdrop-blur-xl shadow-xs overflow-hidden">
      <div class="divide-y divide-zinc-200/60 dark:divide-zinc-800/60">
        <div
          v-for="item in filteredFiles"
          :key="item.id"
          class="flex items-center gap-4 px-5 py-4 hover:bg-zinc-50/80 dark:hover:bg-zinc-800/40 transition-colors"
        >
          <!-- Mime Icon -->
          <div class="size-10 rounded-xl bg-indigo-500/10 text-indigo-500 flex items-center justify-center shrink-0">
            <UIcon :name="mimeIcon(item.originalName, item.mimeType)" class="size-5" />
          </div>

          <!-- Document details -->
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2">
              <span class="font-semibold text-sm text-zinc-900 dark:text-zinc-100 truncate cursor-pointer hover:text-primary-500 transition-colors" @click="openPreview(item)">
                {{ item.originalName }}
              </span>
            </div>

            <div class="flex flex-wrap items-center gap-2.5 text-xs text-zinc-500 dark:text-zinc-400 mt-1">
              <!-- Space Key -->
              <span class="inline-flex items-center gap-1 font-mono">
                <UIcon name="i-lucide-key-round" class="w-3.5 h-3.5 text-indigo-500" />
                <span class="text-zinc-400">Scope:</span>
                <UBadge color="indigo" variant="soft" size="xs" class="font-semibold px-1.5">
                  {{ item.spaceKey || 'RAG' }}
                </UBadge>
              </span>

              <span>·</span>
              <span>{{ formatSize(item.size) }}</span>

              <span>·</span>
              <span class="font-mono text-[11px] text-zinc-400 truncate max-w-[140px]" :title="item.docId">
                ID: {{ item.docId?.slice(0, 8) }}...
              </span>

              <span>·</span>
              <UBadge
                :color="item.visibility === 'shared' ? 'success' : 'neutral'"
                variant="subtle"
                size="xs"
              >
                {{ item.visibility === 'shared' ? 'Public Shared' : 'Private Restricted' }}
              </UBadge>

              <span>·</span>
              <span>{{ formatTime(item.createdAt) }}</span>
            </div>
          </div>

          <!-- Action buttons -->
          <div class="flex items-center gap-1 shrink-0">
            <UButton
              icon="i-lucide-book-open"
              variant="outline"
              size="xs"
              color="primary"
              label="Preview"
              class="rounded-lg shadow-2xs font-medium"
              @click="openPreview(item)"
            />
            <UButton
              icon="i-lucide-shield-cog"
              variant="ghost"
              size="sm"
              color="neutral"
              class="rounded-lg"
              title="Configure Access"
              @click="permissionFile = { id: item.id, originalName: item.originalName, visibility: item.visibility, grants: item.grants }"
            />
            <UButton
              icon="i-lucide-download"
              variant="ghost"
              size="sm"
              color="neutral"
              class="rounded-lg"
              title="Download Document"
              @click="handleDownload(item)"
            />
            <UButton
              icon="i-lucide-trash"
              variant="ghost"
              size="sm"
              color="error"
              class="rounded-lg"
              title="Delete Document"
              @click="handleDelete(item)"
            />
          </div>
        </div>
      </div>
    </div>

    <!-- Modal Preview -->
    <UModal v-model:open="previewOpen" :ui="{ content: 'sm:max-w-3xl' }">
      <template #content>
        <div class="p-6 space-y-4">
          <div class="flex items-start justify-between gap-4 pb-3 border-b border-zinc-200 dark:border-zinc-800">
            <div>
              <div class="flex items-center gap-2">
                <UBadge color="indigo" variant="soft" size="xs">
                  Space: {{ previewDoc?.spaceKey || 'RAG' }}
                </UBadge>
                <h3 class="font-bold text-lg text-zinc-900 dark:text-white truncate max-w-xl">
                  {{ previewDoc?.originalName }}
                </h3>
              </div>
              <p class="text-xs text-zinc-400 mt-1 font-mono">
                Doc ID: {{ previewDoc?.docId }} · {{ formatSize(previewDoc?.size || 0) }} · {{ formatTime(previewDoc?.createdAt || '') }}
              </p>
            </div>
            <UButton
              icon="i-lucide-x"
              color="neutral"
              variant="ghost"
              size="sm"
              @click="previewOpen = false"
            />
          </div>

          <div v-if="previewLoading" class="flex justify-center py-16">
            <UIcon name="i-lucide-loader-circle" class="size-8 animate-spin text-primary-500" />
          </div>

          <div v-else class="max-h-[60vh] overflow-y-auto p-4 rounded-xl bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800">
            <pre class="whitespace-pre-wrap font-sans text-sm text-zinc-800 dark:text-zinc-200 leading-relaxed">{{ previewContent }}</pre>
          </div>

          <div class="flex items-center justify-between pt-2">
            <span class="text-xs text-zinc-400">Access Perimeter: Space [{{ previewDoc?.spaceKey || 'RAG' }}]</span>
            <div class="flex items-center gap-2">
              <UButton
                v-if="previewDoc"
                icon="i-lucide-download"
                variant="outline"
                size="sm"
                color="neutral"
                label="Download"
                class="rounded-xl font-medium"
                @click="handleDownload(previewDoc)"
              />
              <UButton
                color="primary"
                size="sm"
                label="Done"
                class="rounded-xl font-semibold px-4"
                @click="previewOpen = false"
              />
            </div>
          </div>
        </div>
      </template>
    </UModal>

    <!-- Upload dialog -->
    <FilePermissionDialog
      v-if="uploadFile"
      :file="null"
      :upload-file="uploadFile"
      @close="uploadFile = null"
      @saved="onDialogSaved"
    />

    <!-- Edit dialog -->
    <FilePermissionDialog
      v-if="permissionFile"
      :file="permissionFile"
      :upload-file="null"
      @close="permissionFile = null"
      @saved="onDialogSaved"
    />
  </div>
</template>
