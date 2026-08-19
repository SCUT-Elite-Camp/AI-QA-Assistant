<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { $fetch } from 'ofetch'
import { useCsrf } from '../../composables/useCsrf'
import DocumentModal from './DocumentModal.vue'
import AttachmentTray from './AttachmentTray.vue'
import AttachmentEvidenceModal from './AttachmentEvidenceModal.vue'

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
const attachments = ref<any[]>([])
const topicRole = ref<'owner' | 'editor' | 'viewer'>('viewer')
const currentUserId = ref('')
const members = ref<any[]>([])
const memberIdentifier = ref('')
const memberRole = ref<'owner' | 'editor' | 'viewer'>('viewer')
const activeAttachment = ref<any>(null)
const showEvidence = ref(false)

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

async function fetchAttachments() {
  if (!props.topicId) return
  const result = await $fetch<any>(`/api/topics/${props.topicId}/attachments`).catch(() => ({ items: [], role: 'viewer' }))
  attachments.value = result.items || []
  topicRole.value = result.role || 'viewer'
  currentUserId.value = result.current_user_id || ''
  if (topicRole.value === 'owner') await fetchMembers()
}

async function fetchMembers() {
  const result = await $fetch<any>(`/api/topics/${props.topicId}/members`).catch(() => ({ items: [] }))
  members.value = result.items || []
}

async function saveMember(identifier: string, role: 'owner' | 'editor' | 'viewer') {
  const target = identifier.trim()
  if (!target) return
  await $fetch(`/api/topics/${props.topicId}/members/${encodeURIComponent(target)}`, {
    method: 'PUT', headers: { [headerName]: csrf() }, body: { role }
  })
  memberIdentifier.value = ''
  await fetchMembers()
}

async function removeMember(userId: string) {
  await $fetch(`/api/topics/${props.topicId}/members/${encodeURIComponent(userId)}`, {
    method: 'DELETE', headers: { [headerName]: csrf() }
  })
  await fetchMembers()
}

async function removeAttachment(attachment: any) {
  await $fetch(`/api/attachments/${attachment.id}`, { method: 'DELETE', headers: { [headerName]: csrf() } })
  await fetchAttachments()
}

function openEvidence(attachment: any) {
  activeAttachment.value = attachment
  showEvidence.value = true
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
  if (val) { fetchDocuments(); fetchAttachments() }
}, { immediate: true })

onMounted(() => {
  if (props.open) { fetchDocuments(); fetchAttachments() }
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
          <section class="mb-5 rounded-xl border border-zinc-800 p-3">
            <div class="mb-2 flex items-center justify-between">
              <h4 class="text-sm font-medium">Topic 附件池（{{ attachments.length }}）</h4>
              <span class="text-xs text-zinc-500">与知识库引用文档分离</span>
            </div>
            <AttachmentTray v-if="topicRole !== 'viewer'" scope="topic" :topic-id="topicId" @change="fetchAttachments" />
            <div v-for="attachment in attachments" :key="attachment.id" class="mt-2 flex items-center gap-2 rounded border border-zinc-800 p-2 text-xs">
              <button class="min-w-0 flex-1 text-left" @click="openEvidence(attachment)">
                <div class="truncate">{{ attachment.filename }}</div>
                <div class="text-zinc-500">{{ attachment.status }} · Evidence v{{ attachment.evidenceVersion }} · {{ attachment.ownerId }}</div>
              </button>
              <UButton v-if="topicRole === 'owner' || attachment.ownerId === currentUserId" icon="i-lucide-trash-2" size="xs" color="error" variant="ghost" @click="removeAttachment(attachment)" />
            </div>
          </section>
          <section v-if="topicRole === 'owner'" class="mb-5 rounded-xl border border-zinc-800 p-3">
            <h4 class="mb-2 text-sm font-medium">Topic 成员（{{ members.length }}）</h4>
            <div class="mb-3 flex gap-2">
              <UInput v-model="memberIdentifier" class="min-w-0 flex-1" placeholder="用户 ID、邮箱或用户名" />
              <select v-model="memberRole" class="rounded border border-zinc-700 bg-zinc-900 px-2 text-xs">
                <option value="viewer">viewer</option><option value="editor">editor</option><option value="owner">owner</option>
              </select>
              <UButton label="添加" size="xs" @click="saveMember(memberIdentifier, memberRole)" />
            </div>
            <div v-for="member in members" :key="member.userId" class="flex items-center gap-2 border-t border-zinc-800 py-2 text-xs">
              <div class="min-w-0 flex-1"><div class="truncate">{{ member.name || member.username || member.userId }}</div><div class="truncate text-zinc-500">{{ member.email || member.userId }}</div></div>
              <select :value="member.role" class="rounded border border-zinc-700 bg-zinc-900 px-2 py-1" @change="saveMember(member.userId, ($event.target as HTMLSelectElement).value as any)">
                <option value="viewer">viewer</option><option value="editor">editor</option><option value="owner">owner</option>
              </select>
              <UButton icon="i-lucide-user-minus" size="xs" color="error" variant="ghost" @click="removeMember(member.userId)" />
            </div>
          </section>
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
                v-if="topicRole !== 'viewer'"
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
  </UModal>

  <!-- Full Content Viewer Modal -->
  <DocumentModal
    v-if="showPreviewModal && activePreviewDoc"
    v-model:open="showPreviewModal"
    :doc-id="activePreviewDoc.docId"
    :doc-title="cleanTitle(activePreviewDoc)"
    :doc-content="activePreviewDoc.content || activePreviewDoc.snippet"
  />
  <AttachmentEvidenceModal
    v-if="activeAttachment"
    v-model:open="showEvidence"
    :attachment="activeAttachment"
    :can-edit="topicRole !== 'viewer'"
    @updated="fetchAttachments"
  />
</template>
