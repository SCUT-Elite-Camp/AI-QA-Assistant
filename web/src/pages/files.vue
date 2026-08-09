<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { $fetch } from 'ofetch'
import { useCsrf } from '../composables/useCsrf'
import { useUserSession } from '../composables/useUserSession'
import Navbar from '../components/Navbar.vue'

interface FileItem {
  id: string
  userId: string
  name: string
  originalName: string
  mimeType: string
  size: number
  visibility: 'private' | 'shared'
  createdAt: string
}

const toast = useToast()
const { csrf, headerName } = useCsrf()
const { loggedIn, fetchSession } = useUserSession()

const files = ref<FileItem[]>([])
const loading = ref(true)
const uploading = ref(false)
const devLoggingIn = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)

const formatSize = (bytes: number): string => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

const formatTime = (iso: string): string => {
  const d = new Date(iso)
  const pad = (n: number) => n.toString().padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const mimeIcon = (mime: string): string => {
  if (mime.startsWith('image/')) return 'i-lucide-image'
  if (mime.includes('pdf')) return 'i-lucide-file-text'
  if (mime.includes('word') || mime.includes('document')) return 'i-lucide-file-text'
  if (mime.includes('sheet') || mime.includes('excel')) return 'i-lucide-table'
  if (mime.includes('presentation') || mime.includes('powerpoint')) return 'i-lucide-presentation'
  if (mime.startsWith('text/')) return 'i-lucide-file'
  if (mime.includes('zip') || mime.includes('tar') || mime.includes('gzip')) return 'i-lucide-archive'
  return 'i-lucide-file'
}

async function loadFiles() {
  loading.value = true
  try {
    files.value = await $fetch<FileItem[]>('/api/files')
  } catch (err: any) {
    console.error('[loadFiles] 加载文件列表失败:', err)
    toast.add({ title: '加载文件列表失败', color: 'error' })
  } finally {
    loading.value = false
  }
}

async function handleUpload(fileList: FileList | null) {
  if (!fileList || fileList.length === 0) return
  if (!loggedIn.value) {
    toast.add({ title: '请先登录后再上传文件', color: 'error' })
    return
  }

  uploading.value = true
  const file = fileList[0]

  const formData = new FormData()
  formData.append('file', file)

  try {
    await $fetch('/api/files', {
      method: 'POST',
      headers: { [headerName]: csrf() },
      body: formData,
    })
    toast.add({ title: `已上传: ${file.name}`, color: 'success' })
    await loadFiles()
  } catch (err: any) {
    const status = err?.response?.status
    const msg = status === 401 ? '未登录，无法上传' : status === 403 ? 'CSRF 校验失败，请刷新后重试' : '上传失败'
    toast.add({ title: msg, color: 'error' })
  } finally {
    uploading.value = false
  }
}

async function handleDownload(item: FileItem) {
  window.open(`/api/files/${item.id}?download=1`, '_blank')
}

async function handleDelete(item: FileItem) {
  if (!confirm(`确定要删除 "${item.originalName}" 吗？`)) return
  try {
    await $fetch(`/api/files/${item.id}`, {
      method: 'DELETE',
      headers: { [headerName]: csrf() },
    })
    toast.add({ title: '已删除', color: 'success' })
    await loadFiles()
  } catch (err: any) {
    const status = err?.response?.status
    const msg = status === 401 ? '未登录，无法操作' : status === 403 ? 'CSRF 校验失败，请刷新后重试' : '删除失败'
    toast.add({ title: msg, color: 'error' })
  }
}

onMounted(() => {
  loadFiles()
  fetchSession()
})

async function devLogin() {
  devLoggingIn.value = true
  try {
    await $fetch('/api/auth/dev-login', {
      method: 'POST',
      headers: { [headerName]: csrf() },
      body: {},
    })
    await fetchSession()
    await loadFiles()
    toast.add({ title: '开发登录成功', color: 'success', icon: 'i-lucide-check' })
  } catch (err: any) {
    const msg = err?.response?.status === 403
      ? '开发登录未启用，请在 .env 中设置 ALLOW_DEV_LOGIN=true'
      : '开发登录失败'
    toast.add({ title: msg, color: 'error', icon: 'i-lucide-x' })
  } finally {
    devLoggingIn.value = false
  }
}
</script>

<template>
  <UDashboardPanel
    id="files"
    class="min-h-0"
    :ui="{ body: 'p-0 sm:p-0' }"
  >
    <template #header>
      <Navbar />
    </template>

    <template #body>
      <UContainer class="flex-1 py-8 max-w-3xl">
        <div class="flex items-center justify-between mb-8">
          <div>
            <h1 class="text-2xl font-bold text-highlighted">文件管理</h1>
            <p class="text-dimmed mt-1">上传、查看和管理您的文件。</p>
          </div>
          <div>
            <input
              ref="fileInputRef"
              type="file"
              class="hidden"
              :disabled="!loggedIn"
              @change="handleUpload(($event.target as HTMLInputElement).files)"
            />
            <button
              type="button"
              :disabled="!loggedIn || uploading"
              class="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-md bg-primary text-primary-contrast hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer transition-colors"
              @click="fileInputRef?.click()"
            >
              <UIcon
                :name="uploading ? 'i-lucide-loader' : 'i-lucide-upload'"
                :class="['size-4', uploading && 'animate-spin']"
              />
              上传文件
            </button>
          </div>
        </div>

        <UAlert
          v-if="!loading && !loggedIn && !devLoggingIn"
          color="warning"
          icon="i-lucide-alert-circle"
          title="未登录"
          description="当前为预览模式，登录后才能上传和管理文件。"
          :actions="[{ label: '开发登录', size: 'xs', color: 'warning', variant: 'outline', icon: 'i-lucide-log-in', loading: devLoggingIn, onClick: devLogin }]"
        />

        <!-- Loading -->
        <div v-if="loading" class="flex justify-center py-16">
          <UIcon name="i-lucide-loader" class="animate-spin size-6" />
        </div>

        <!-- Empty -->
        <div v-else-if="files.length === 0" class="text-center py-16 text-dimmed">
          <UIcon name="i-lucide-folder-open" class="size-12 mx-auto mb-3 opacity-40" />
          <p>暂无文件</p>
          <p class="text-sm">点击上方「上传文件」按钮添加文件。</p>
        </div>

        <!-- File list -->
        <div v-else class="space-y-2">
          <div
            v-for="item in files"
            :key="item.id"
            class="flex items-center gap-3 p-3 rounded-xl border border-border hover:bg-bg-elevated transition-colors"
          >
            <!-- Icon -->
            <div class="size-10 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
              <UIcon :name="mimeIcon(item.mimeType)" class="size-5 text-primary" />
            </div>

            <!-- Info -->
            <div class="flex-1 min-w-0">
              <div class="font-medium truncate text-highlighted">{{ item.originalName }}</div>
              <div class="flex gap-3 text-xs text-dimmed mt-0.5">
                <span>{{ formatSize(item.size) }}</span>
                <span>{{ item.visibility === 'shared' ? '共享' : '私有' }}</span>
                <span>{{ formatTime(item.createdAt) }}</span>
              </div>
            </div>

            <!-- Actions -->
            <div class="flex items-center gap-1">
              <UButton
                icon="i-lucide-eye"
                variant="ghost"
                size="sm"
                color="neutral"
                @click="window.open(`/api/files/${item.id}`, '_blank')"
              />
              <UButton
                icon="i-lucide-download"
                variant="ghost"
                size="sm"
                color="neutral"
                @click="handleDownload(item)"
              />
              <UButton
                icon="i-lucide-trash"
                variant="ghost"
                size="sm"
                color="error"
                @click="handleDelete(item)"
              />
            </div>
          </div>
        </div>
      </UContainer>
    </template>
  </UDashboardPanel>
</template>
