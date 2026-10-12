<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { $fetch } from 'ofetch'
import { useCsrf } from '../../composables/useCsrf'
import { attachmentErrorCode, attachmentErrorMessage } from '../../utils/attachmentError'

type Scope = 'draft' | 'chat' | 'topic'
interface TrayAttachment {
  id?: string
  filename: string
  mimeType: string
  sizeBytes: number
  progress: number
  status: string
  errorCode?: string
  acceptedReview?: boolean
  expiresAt?: number
  xhr?: XMLHttpRequest
  cancelled?: boolean
  file?: File
  pollFailures?: number
}

const props = withDefaults(defineProps<{
  scope: Scope
  chatId?: string | null
  topicId?: string | null
  disabled?: boolean
  hideTrigger?: boolean
}>(), {
  hideTrigger: false
})
const emit = defineEmits<{
  change: [ids: string[], acceptedNeedsReviewIds: string[]]
  'count-change': [count: number]
}>()
const { csrf, headerName } = useCsrf()
const inputRef = ref<HTMLInputElement | null>(null)
const items = ref<TrayAttachment[]>([])
watch(() => items.value.length, (count) => {
  emit('count-change', count)
})
const batchId = ref<string | null>(null)
let batchPromise: Promise<string> | null = null
const polling = new Map<string, ReturnType<typeof setTimeout>>()
const serviceEnabled = ref(false)

const MIME_BY_EXTENSION: Record<string, string> = {
  png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp',
  bmp: 'image/bmp', tif: 'image/tiff', tiff: 'image/tiff', pdf: 'application/pdf',
  doc: 'application/msword',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  ppt: 'application/vnd.ms-powerpoint',
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  xls: 'application/vnd.ms-excel',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  html: 'text/html', htm: 'text/html', csv: 'text/csv', txt: 'text/plain',
  md: 'text/markdown', json: 'application/json',
}

function controlledMime(file: File): string {
  if (file.type) return file.type.split(';', 1)[0]!.toLowerCase()
  const extension = file.name.split('.').pop()?.toLowerCase() || ''
  return MIME_BY_EXTENSION[extension] || 'application/octet-stream'
}

function statusText(item: TrayAttachment): string {
  const labels: Record<string, string> = {
    uploading: 'Uploading...',
    scanning: 'Processing...',
    parsing: 'Processing...',
    chunking: 'Processing...',
    embedding: 'Indexing...',
    indexing: 'Indexing...',
    ready: 'Ready',
    needs_review: 'Review needed',
    failed: 'Failed',
    quarantined: 'Quarantined',
    expired: 'Expired',
    deleted: 'Deleted',
    cancelled: 'Cancelled',
  }
  return labels[item.status] || item.status
}

const selectedIds = computed(() => items.value.filter(item => item.id && (item.status === 'ready' || (item.status === 'needs_review' && item.acceptedReview))).map(item => item.id!))

function notify() {
  emit('change', selectedIds.value, items.value.filter(item => item.id && item.status === 'needs_review' && item.acceptedReview).map(item => item.id!))
}

async function ensureBatch(): Promise<string> {
  if (batchId.value) return batchId.value
  if (!batchPromise) {
    batchPromise = $fetch<any>('/api/attachment-batches', {
      method: 'POST', headers: { [headerName]: csrf() },
      body: { scope: props.scope, chat_id: props.chatId || null, topic_id: props.topicId || null }
    }).then((batch) => {
      batchId.value = batch.id
      return batch.id as string
    }).finally(() => { batchPromise = null })
  }
  return batchPromise
}

function uploadFile(file: File, existing?: TrayAttachment) {
  if (!existing && items.value.length >= 10) return
  const item = existing || reactive<TrayAttachment>({ filename: file.name, mimeType: controlledMime(file), sizeBytes: file.size, progress: 0, status: 'uploading', file })
  if (!existing) items.value.push(item)
  item.cancelled = false
  item.status = 'uploading'
  item.errorCode = ''
  item.progress = 0
  notify()
  ensureBatch().then((id) => {
    if (item.cancelled) return
    const xhr = new XMLHttpRequest()
    item.xhr = xhr
    xhr.open('POST', `/api/attachment-batches/${id}/files`)
    xhr.timeout = 180_000
    xhr.setRequestHeader(headerName, csrf())
    const filenameBytes = new TextEncoder().encode(file.name)
    let filenameBinary = ''
    for (const byte of filenameBytes) filenameBinary += String.fromCharCode(byte)
    xhr.setRequestHeader('X-File-Name-B64', btoa(filenameBinary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''))
    xhr.setRequestHeader('Content-Type', item.mimeType)
    xhr.upload.onprogress = event => { if (event.lengthComputable) item.progress = Math.round(event.loaded * 100 / event.total) }
    xhr.onerror = () => { item.status = 'failed'; item.errorCode = 'network_error'; notify() }
    xhr.ontimeout = () => { item.status = 'failed'; item.errorCode = 'upload_timeout'; notify() }
    xhr.onabort = () => { item.status = 'cancelled'; notify() }
    xhr.onload = () => {
      let payload: any = {}
      try { payload = JSON.parse(xhr.responseText || '{}') } catch {}
      if (item.cancelled) {
        if (payload?.id) {
          $fetch(`/api/attachments/${payload.id}`, {
            method: 'DELETE', headers: { [headerName]: csrf() },
          }).catch(() => undefined)
        }
        return
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        item.status = 'failed'; item.errorCode = attachmentErrorCode(payload); notify(); return
      }
      item.id = payload.id
      item.status = payload.status || 'parsing'
      item.expiresAt = payload.expires_at
      item.errorCode = payload.error_code || ''
      item.progress = 100
      notify()
      poll(item)
    }
    xhr.send(file)
  }).catch((error) => { item.status = 'failed'; item.errorCode = attachmentErrorCode(error?.data, 'batch_failed'); notify() })
}

async function poll(item: TrayAttachment) {
  if (item.cancelled) return
  if (!item.id || ['ready', 'needs_review', 'failed', 'quarantined', 'expired', 'deleted'].includes(item.status)) { notify(); return }
  try {
    const result = await $fetch<any>(`/api/attachments/${item.id}`)
    item.status = result.status
    item.errorCode = result.error_code || ''
    item.pollFailures = 0
  } catch {
    item.pollFailures = (item.pollFailures || 0) + 1
    if (item.pollFailures >= 3) { item.status = 'failed'; item.errorCode = 'status_unavailable' }
  }
  notify()
  if (!item.cancelled && !['ready', 'needs_review', 'failed', 'quarantined', 'expired', 'deleted'].includes(item.status)) {
    polling.set(item.id, setTimeout(() => poll(item), 1500))
  }
}

function addFiles(files: FileList | File[]) {
  if (props.disabled) return
  Array.from(files).slice(0, 10 - items.value.length).forEach(file => uploadFile(file))
  if (inputRef.value) inputRef.value.value = ''
}

async function remove(item: TrayAttachment) {
  item.cancelled = true
  item.xhr?.abort()
  if (item.id && polling.has(item.id)) {
    clearTimeout(polling.get(item.id))
    polling.delete(item.id)
  }
  if (item.id) await $fetch(`/api/attachments/${item.id}`, { method: 'DELETE', headers: { [headerName]: csrf() } }).catch(() => undefined)
  items.value = items.value.filter(value => value !== item)
  notify()
}

function retry(item: TrayAttachment) {
  if (!item.id) {
    if (item.errorCode === 'batch_expired') batchId.value = null
    if (item.file) uploadFile(item.file, item)
    return
  }
  const statusOnly = item.errorCode === 'status_unavailable'
  item.status = 'parsing'
  item.errorCode = ''
  item.pollFailures = 0
  notify()
  if (statusOnly) { poll(item); return }
  $fetch(`/api/attachments/${item.id}/retry`, { method: 'POST', headers: { [headerName]: csrf() } })
    .then(() => poll(item)).catch((error) => { item.status = 'failed'; item.errorCode = attachmentErrorCode(error?.data, 'parse_failed'); notify() })
}

function onPaste(event: ClipboardEvent) {
  if (!props.disabled && event.clipboardData?.files?.length) addFiles(event.clipboardData.files)
}

function resetAfterSend() {
  polling.forEach(timer => clearTimeout(timer))
  polling.clear()
  items.value = []
  batchId.value = null
  batchPromise = null
  notify()
}

function hasBlockingAttachments(): boolean {
  return items.value.some(item =>
    ['uploading', 'scanning', 'parsing', 'chunking', 'embedding', 'indexing'].includes(item.status)
    || (item.status === 'needs_review' && !item.acceptedReview),
  )
}

onMounted(async () => {
  window.addEventListener('paste', onPaste)
  try {
    const status = await $fetch<any>('/api/attachments/status').catch(() => ({ enabled: true }))
    serviceEnabled.value = status.enabled !== false
  } catch {
    serviceEnabled.value = true
  }
})
onBeforeUnmount(() => {
  window.removeEventListener('paste', onPaste)
  polling.forEach(timer => clearTimeout(timer))
  items.value.forEach(item => { item.cancelled = true; item.xhr?.abort() })
})
defineExpose({
  open: () => {
    if (!props.disabled) {
      inputRef.value?.click()
    }
  },
  resetAfterSend,
  hasBlockingAttachments,
})
</script>

<template>
  <div :class="[items.length ? 'w-full' : (hideTrigger ? 'hidden' : 'w-auto')]" @dragover.prevent @drop.prevent="addFiles($event.dataTransfer?.files || [])">
    <UButton
      v-if="!hideTrigger"
      icon="i-lucide-paperclip"
      color="neutral"
      variant="ghost"
      size="sm"
      :disabled="disabled || !serviceEnabled"
      :title="serviceEnabled ? 'Upload files or images' : 'Attachment service unavailable'"
      aria-label="Upload files or images"
      @click="inputRef?.click()"
    />
    <input
      ref="inputRef"
      class="hidden"
      type="file"
      multiple
      accept=".png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff,.pdf,.doc,.docx,.ppt,.pptx,.html,.htm,.xls,.xlsx,.csv,.txt,.md,.json"
      @change="addFiles(($event.target as HTMLInputElement).files || [])"
    >
    <div v-if="items.length" class="flex flex-wrap gap-2 pb-2">
      <div v-for="item in items" :key="item.id || item.filename" class="max-w-64 rounded-xl border border-default bg-elevated/40 backdrop-blur-xs px-2.5 py-1.5 text-xs shadow-xs">
        <div class="flex items-center gap-1.5">
          <UIcon :name="item.mimeType.startsWith('image/') ? 'i-lucide-image' : 'i-lucide-file'" class="size-3.5 shrink-0 text-primary" aria-hidden="true" />
          <span class="truncate font-medium">{{ item.filename }}</span>
          <UButton icon="i-lucide-x" size="xs" color="neutral" variant="ghost" class="ml-auto rounded-full p-0.5 hover:bg-neutral/20" :aria-label="`Remove ${item.filename}`" @click="remove(item)" />
        </div>
        <div class="text-muted text-[11px] mt-0.5" role="status" aria-live="polite">
          {{ statusText(item) }} · {{ Math.ceil(item.sizeBytes / 1024) }} KB
          <span v-if="item.status === 'uploading'"> · {{ item.progress }}%</span>
        </div>
        <div v-if="item.expiresAt" class="text-muted text-[10px]">Expires: {{ new Date(item.expiresAt * 1000).toLocaleString() }}</div>
        <div v-if="item.errorCode" class="text-error text-[11px]">{{ attachmentErrorMessage(item.errorCode) }}</div>
        <div v-if="item.status === 'needs_review'" class="mt-1 flex items-center gap-1 text-[11px]">
          <input v-model="item.acceptedReview" type="checkbox" @change="notify"><span>Confirm low-confidence result</span>
        </div>
        <UButton v-if="item.status === 'failed' && (item.id || item.file)" label="Retry" size="xs" variant="soft" color="error" class="mt-1" @click="retry(item)" />
      </div>
    </div>
  </div>
</template>
