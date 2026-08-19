<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { $fetch } from 'ofetch'
import Navbar from '../../components/Navbar.vue'
import { useCsrf } from '../../composables/useCsrf'

type LibraryFile = {
  id: string
  displayName: string
  filename: string
  status: string
  error_code?: string
  latest_version_id?: string
}

const files = ref<LibraryFile[]>([])
const loading = ref(false)
const uploading = ref(false)
const picker = ref<HTMLInputElement | null>(null)
const updatingDocumentId = ref<string | null>(null)
const { csrf, headerName } = useCsrf()
const toast = useToast()
let pollTimer: ReturnType<typeof setInterval> | undefined

async function loadFiles() {
  loading.value = true
  try {
    const result = await $fetch<{ files: LibraryFile[] }>('/api/library/files')
    files.value = result.files
  } finally {
    loading.value = false
  }
}

async function refreshProcessing() {
  const pending = files.value.filter(item => !['READY', 'FAILED'].includes(item.status))
  await Promise.all(pending.map(async item => {
    try {
      const status = await $fetch<any>(`/api/library/files/${item.id}/status`)
      item.status = status.status
      item.error_code = status.error_code
    } catch {}
  }))
}

async function upload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || uploading.value) return
  uploading.value = true
  try {
    await $fetch('/api/library/files', {
      method: 'POST',
      headers: {
        [headerName]: csrf(),
        'content-type': file.type || 'application/octet-stream',
        'content-length': String(file.size),
        'x-file-name-b64': btoa(unescape(encodeURIComponent(file.name))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''),
        ...(updatingDocumentId.value ? { 'x-document-id': updatingDocumentId.value } : {})
      },
      body: file
    })
    await loadFiles()
  } catch (error) {
    toast.add({ color: 'error', description: error instanceof Error ? error.message : '上传失败' })
  } finally {
    uploading.value = false
    input.value = ''
    updatingDocumentId.value = null
  }
}

function chooseNewFile() {
  updatingDocumentId.value = null
  picker.value?.click()
}

function chooseUpdate(item: LibraryFile) {
  updatingDocumentId.value = item.id
  picker.value?.click()
}

async function remove(item: LibraryFile) {
  await $fetch(`/api/library/files/${item.id}`, { method: 'DELETE', headers: { [headerName]: csrf() } })
  files.value = files.value.filter(file => file.id !== item.id)
}

async function reindex(item: LibraryFile) {
  await $fetch(`/api/library/files/${item.id}/reindex`, { method: 'POST', headers: { [headerName]: csrf() } })
  item.status = 'REINDEXING'
}

onMounted(async () => {
  await loadFiles()
  pollTimer = setInterval(refreshProcessing, 2000)
})
onUnmounted(() => { if (pollTimer) clearInterval(pollTimer) })
</script>

<template>
  <UDashboardPanel id="library">
    <template #header>
      <Navbar>
        <template #title>
          <span class="font-semibold">我的资料库</span>
        </template>
      </Navbar>
    </template>
    <template #body>
      <UContainer class="py-16 max-w-4xl">
        <div class="flex items-center justify-between mb-6">
          <div>
            <h1 class="text-2xl font-bold">
              Personal Knowledge Library
            </h1>
            <p class="text-sm text-muted mt-1">
              长期保存个人文件，并在聊天中通过“我的资料库”检索。
            </p>
          </div>
          <input
            ref="picker"
            type="file"
            class="hidden"
            @change="upload"
          >
          <UButton
            icon="i-lucide-upload"
            :loading="uploading"
            @click="chooseNewFile"
          >
            上传文件
          </UButton>
        </div>
        <div
          v-if="loading"
          class="py-10 text-center text-muted"
        >
          正在加载…
        </div>
        <div
          v-else-if="!files.length"
          class="border border-dashed rounded-xl py-16 text-center text-muted"
        >
          还没有文件
        </div>
        <div
          v-else
          class="space-y-2"
        >
          <div
            v-for="item in files"
            :key="item.id"
            class="border rounded-xl p-4 flex items-center gap-4"
          >
            <UIcon
              name="i-lucide-file-text"
              class="size-6"
            />
            <div class="min-w-0 flex-1">
              <div class="font-medium truncate">
                {{ item.displayName || item.filename }}
              </div>
              <div class="text-xs text-muted">
                {{ item.status }}<span v-if="item.error_code"> · {{ item.error_code }}</span>
              </div>
            </div>
            <UButton
              color="neutral"
              variant="ghost"
              icon="i-lucide-upload-cloud"
              aria-label="上传新版本"
              @click="chooseUpdate(item)"
            />
            <UButton
              v-if="item.status === 'FAILED'"
              color="neutral"
              variant="ghost"
              icon="i-lucide-refresh-cw"
              @click="reindex(item)"
            />
            <UButton
              color="error"
              variant="ghost"
              icon="i-lucide-trash-2"
              @click="remove(item)"
            />
          </div>
        </div>
      </UContainer>
    </template>
  </UDashboardPanel>
</template>
