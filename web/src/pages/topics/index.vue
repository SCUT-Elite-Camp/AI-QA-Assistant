<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, defineAsyncComponent } from 'vue'
import { useRouter } from 'vue-router'
import { $fetch } from 'ofetch'
import { useCsrf } from '../../composables/useCsrf'

const TopicDocumentPool = defineAsyncComponent(() => import('../../components/chat/TopicDocumentPool.vue'))
const DocumentModal = defineAsyncComponent(() => import('../../components/chat/DocumentModal.vue'))

const router = useRouter()
const toast = useToast()
const overlay = useOverlay()
const { csrf, headerName } = useCsrf()

const topics = ref<any[]>([])
const loading = ref(true)
const searchQuery = ref('')

const showCreateModal = ref(false)
const newTopicTitle = ref('')
const creating = ref(false)

// Document Pool Viewer Modal State
const showDocsModal = ref(false)
const selectedDocsTopicId = ref('')

function openDocsModal(topic: any) {
  selectedDocsTopicId.value = topic.id
  showDocsModal.value = true
}

// Single document preview modal state
const showSingleDocModal = ref(false)
const selectedDocForModal = ref<any>(null)

function openSingleDocModal(doc: any, event?: Event) {
  if (event) event.stopPropagation()
  selectedDocForModal.value = doc
  showSingleDocModal.value = true
}

function cleanDocTitle(doc: any): string {
  if (!doc) return ''
  let title = doc.title || doc.docId || ''
  return title.replace(/^[a-f0-9]{32}_/i, '').replace(/^[a-f0-9-]{36}_/i, '')
}

// Gemini Gems Wide Modal Settings State
const showSettingsModal = ref(false)
const selectedTopic = ref<any>(null)

const editedTitle = ref('')
const editedDescription = ref('')
const localSoul = ref('')
const selectedWeightMode = ref<'deeper' | 'auto' | 'wider'>('auto')
const isSaving = ref(false)
const isSummarizing = ref(false)

// Content Tags State (Light Blue Keywords)
const topicTags = ref<string[]>([])
const newTagInput = ref('')
const isAddingTag = ref(false)
const tagInputRef = ref<HTMLInputElement | null>(null)

function triggerAddTag() {
  isAddingTag.value = true
  nextTick(() => {
    tagInputRef.value?.focus()
  })
}

function handleConfirmAddTag() {
  const val = newTagInput.value.trim()
  if (val && !topicTags.value.includes(val)) {
    topicTags.value.push(val)
  }
  newTagInput.value = ''
  isAddingTag.value = false
}

function removeTag(index: number) {
  topicTags.value.splice(index, 1)
}

// File Upload & Knowledge State inside Settings
const topicDocs = ref<any[]>([])
const loadingDocs = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)
const uploadingFile = ref(false)

let pollTimer: any = null

function checkPolling() {
  const hasGenerating = (topics.value || []).some((t: any) => t.status === 'generating')
  if (hasGenerating && !pollTimer) {
    pollTimer = setInterval(async () => {
      try {
        const fresh: any = await $fetch('/api/topics')
        topics.value = fresh
        if (!fresh.some((t: any) => t.status === 'generating')) {
          clearInterval(pollTimer)
          pollTimer = null
        }
      } catch (e) {}
    }, 2500)
  } else if (!hasGenerating && pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function fetchTopics() {
  loading.value = true
  try {
    topics.value = await $fetch('/api/topics')
    checkPolling()
  } catch (err: any) {
    toast.add({ title: 'Failed to fetch topics', description: err.message, color: 'error' })
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchTopics()
})

onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})

const filteredTopics = computed(() => {
  let list = topics.value || []
  if (searchQuery.value.trim()) {
    const q = searchQuery.value.trim().toLowerCase()
    list = list.filter(t => t.title?.toLowerCase().includes(q))
  }
  return list
})

async function handleCreateTopic() {
  if (!newTopicTitle.value.trim() || creating.value) return
  creating.value = true
  try {
    const topic: any = await $fetch('/api/topics', {
      method: 'POST',
      headers: { [headerName]: csrf() },
      body: { title: newTopicTitle.value.trim() }
    })
    toast.add({ title: 'Topic created successfully', color: 'success' })
    showCreateModal.value = false
    newTopicTitle.value = ''
    if (topic?.mainChatId) {
      router.push(`/chat/${topic.mainChatId}`)
    } else {
      await fetchTopics()
    }
  } catch (err: any) {
    toast.add({ title: 'Failed to create topic', description: err.message, color: 'error' })
  } finally {
    creating.value = false
  }
}

async function openSettingsModal(topic: any) {
  selectedTopic.value = topic
  editedTitle.value = topic.title || ''
  editedDescription.value = topic.description || ''
  localSoul.value = topic.soulContent || ''
  selectedWeightMode.value = topic.weightMode || 'auto'
  topicTags.value = Array.isArray(topic.tags) ? [...topic.tags] : []
  showSettingsModal.value = true

  // Fetch Topic Documents
  loadingDocs.value = true
  try {
    const topicData: any = await $fetch(`/api/topics/${topic.id}`)
    topicDocs.value = (topicData?.documents || []).filter((d: any) => !d.isRemoved)
    if (topicData?.description) {
      editedDescription.value = topicData.description
    }
    if (topicData?.tags && Array.isArray(topicData.tags)) {
      topicTags.value = [...topicData.tags]
    }
  } catch (e) {
    topicDocs.value = []
  } finally {
    loadingDocs.value = false
  }
}

async function handleTriggerSummarize() {
  if (!selectedTopic.value?.id || isSummarizing.value) return
  const topicId = selectedTopic.value.id

  // 1. Immediately mark target topic card as 'generating' so it shows spinning icon
  const targetTopic = topics.value.find(t => t.id === topicId)
  if (targetTopic) {
    targetTopic.status = 'generating'
  }

  // 2. Gracefully exit settings modal
  showSettingsModal.value = false
  toast.add({ title: 'Summarization submitted', description: 'Data persistence layer is synthesizing topic cognition...', color: 'info' })

  // 3. Start polling & trigger background summarizer call
  checkPolling()
  try {
    await $fetch(`/api/topics/${topicId}/summarize`, {
      method: 'POST',
      headers: { [headerName]: csrf() }
    })
    await fetchTopics()
  } catch (e: any) {
    if (targetTopic) targetTopic.status = 'ready'
    toast.add({ title: 'Summarization failed', description: e.message, color: 'error' })
  }
}

async function handleSaveSettings() {
  if (!selectedTopic.value?.id || isSaving.value) return
  isSaving.value = true
  try {
    const updated: any = await $fetch(`/api/topics/${selectedTopic.value.id}`, {
      method: 'PATCH',
      headers: { [headerName]: csrf() },
      body: {
        title: editedTitle.value.trim() || selectedTopic.value.title,
        soulContent: localSoul.value,
        weightMode: selectedWeightMode.value,
        tags: topicTags.value
      }
    })
    selectedTopic.value.title = updated.title
    selectedTopic.value.soulContent = updated.soulContent
    selectedTopic.value.weightMode = updated.weightMode
    selectedTopic.value.tags = updated.tags
    toast.add({ title: 'Settings saved successfully', color: 'success' })
    showSettingsModal.value = false
    await fetchTopics()
  } catch (e: any) {
    toast.add({ title: 'Failed to save settings', description: e.message, color: 'error' })
  } finally {
    isSaving.value = false
  }
}

function triggerFilePicker() {
  fileInputRef.value?.click()
}

async function handleFileUpload(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file || !selectedTopic.value?.id) return

  uploadingFile.value = true
  try {
    const textContent = await file.text()
    await $fetch(`/api/topics/${selectedTopic.value.id}/documents`, {
      method: 'POST',
      headers: { [headerName]: csrf() },
      body: {
        title: file.name,
        content: textContent
      }
    })
    toast.add({
      title: 'Document uploaded successfully',
      description: `Path: data-persistence/data/topics/${selectedTopic.value.id}/documents/${file.name}`,
      color: 'success'
    })
    // Refresh doc list
    const topicData: any = await $fetch(`/api/topics/${selectedTopic.value.id}`)
    topicDocs.value = (topicData?.documents || []).filter((d: any) => !d.isRemoved)
  } catch (e: any) {
    toast.add({ title: 'Failed to upload document', description: e.message, color: 'error' })
  } finally {
    uploadingFile.value = false
    if (target) target.value = ''
  }
}

async function handleDeleteDoc(docId: string) {
  try {
    await $fetch(`/api/topics/${selectedTopic.value.id}/documents/${docId}`, {
      method: 'DELETE',
      headers: { [headerName]: csrf() }
    })
    toast.add({ title: 'Document removed successfully', color: 'success' })
    topicDocs.value = topicDocs.value.filter(d => d.docId !== docId)
  } catch (e: any) {
    toast.add({ title: 'Failed to remove document', description: e.message, color: 'error' })
  }
}

async function handleDeleteTopic(topic: any) {
  try {
    await $fetch(`/api/topics/${topic.id}`, {
      method: 'DELETE',
      headers: { [headerName]: csrf() }
    })
    toast.add({ title: 'Topic deleted successfully', color: 'success' })
    if (selectedTopic.value?.id === topic.id) {
      showSettingsModal.value = false
    }
    await fetchTopics()
  } catch (e: any) {
    toast.add({ title: 'Failed to delete topic', description: e.message, color: 'error' })
  }
}
</script>

<template>
  <div class="flex-1 flex flex-col min-w-0 bg-zinc-950 p-6 md:p-10 overflow-y-auto">
    <!-- Header -->
    <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-zinc-800/80">
      <div>
        <div class="flex items-center gap-2.5">
          <div class="w-8 h-8 rounded-lg bg-emerald-500/10 text-emerald-400 flex items-center justify-center font-bold">
            <UIcon name="i-heroicons-squares-2x2" class="w-5 h-5" />
          </div>
          <h1 class="text-2xl font-bold text-zinc-100 tracking-tight">Topics</h1>
        </div>
      </div>

      <div class="flex items-center gap-3">
        <UInput
          v-model="searchQuery"
          icon="i-heroicons-magnifying-glass"
          placeholder="Search..."
          size="sm"
          class="w-56"
        />
        <UButton
          color="emerald"
          icon="i-heroicons-plus"
          size="sm"
          class="font-semibold shadow-xs"
          @click="showCreateModal = true"
        >
          New
        </UButton>
      </div>
    </div>

    <!-- Loading State -->
    <div v-if="loading" class="py-20 text-center text-zinc-400 text-sm flex items-center justify-center gap-2">
      <UIcon name="i-heroicons-arrow-path" class="w-5 h-5 animate-spin text-emerald-500" />
      <span>Loading...</span>
    </div>

    <!-- Empty State -->
    <div v-else-if="!filteredTopics.length" class="py-20 text-center space-y-3 bg-zinc-900/40 rounded-2xl border border-zinc-800/80 my-8">
      <UIcon name="i-heroicons-folder-open" class="w-12 h-12 text-zinc-700 mx-auto" />
      <h3 class="text-sm font-semibold text-zinc-300">No Topics</h3>
      <UButton
        color="emerald"
        variant="soft"
        size="xs"
        icon="i-heroicons-plus"
        @click="showCreateModal = true"
      >
        New Topic
      </UButton>
    </div>

    <!-- Topic Cards List (Clean & Minimalist: Avatar + Title Only) -->
    <div v-else class="space-y-3 my-6">
      <div
        v-for="topic in filteredTopics"
        :key="topic.id"
        class="group p-4 bg-zinc-900/80 hover:bg-zinc-900 border border-zinc-800/90 hover:border-emerald-500/40 rounded-2xl shadow-xs transition-all flex items-center justify-between gap-4"
      >
        <!-- Left: Icon + Title Only -->
        <div
          class="flex items-center gap-3.5 min-w-0 flex-1 cursor-pointer"
          @click="router.push(`/chat/${topic.mainChatId}`)"
        >
          <div class="w-10 h-10 rounded-xl bg-emerald-500/10 text-emerald-400 flex items-center justify-center font-bold text-base shrink-0 group-hover:scale-105 transition-transform">
            {{ topic.title ? topic.title.slice(0, 1) : 'T' }}
          </div>

          <div class="min-w-0">
            <h3 class="text-sm font-bold text-zinc-100 group-hover:text-emerald-400 transition-colors truncate">
              {{ topic.title }}
            </h3>

            <!-- Horizontal Document Pills on Topic Cards -->
            <div v-if="topic.documents && topic.documents.length" class="flex flex-wrap items-center gap-1.5 mt-1.5">
              <div
                v-for="doc in topic.documents"
                :key="doc.docId || doc.id"
                class="flex items-center gap-1.5 px-2.5 py-1 bg-zinc-800/90 hover:bg-zinc-800 border border-zinc-700/60 hover:border-emerald-500/50 rounded-lg text-[11px] cursor-pointer transition-all shadow-2xs group/doc"
                @click.stop="openSingleDocModal(doc, $event)"
              >
                <UIcon name="i-heroicons-document-text" class="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                <span class="font-medium text-zinc-200 group-hover/doc:text-white truncate max-w-[180px]" :title="cleanDocTitle(doc)">
                  {{ cleanDocTitle(doc) }}
                </span>
              </div>
            </div>
          </div>
        </div>


        <!-- Right Pure Icon Actions -->
        <UTooltip v-if="topic.status === 'generating'" text="Generating topic summary...">
          <div class="flex items-center justify-center w-8 h-8 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 shrink-0 shadow-2xs">
            <UIcon name="i-heroicons-arrow-path" class="w-4 h-4 animate-spin text-emerald-400" />
          </div>
        </UTooltip>

        <div v-else class="flex items-center gap-1 shrink-0">
          <UTooltip text="View Document Pool">
            <UButton
              color="neutral"
              variant="ghost"
              icon="i-heroicons-folder-open"
              size="sm"
              class="text-zinc-400 hover:text-white"
              @click="openDocsModal(topic)"
            />
          </UTooltip>

          <UTooltip text="Edit Settings">
            <UButton
              color="neutral"
              variant="ghost"
              icon="i-heroicons-pencil"
              size="sm"
              class="text-zinc-400 hover:text-white"
              @click="openSettingsModal(topic)"
            />
          </UTooltip>

          <UDropdownMenu
            :items="[[
              { label: 'Open Chat', icon: 'i-heroicons-chat-bubble-left-right', onSelect: () => router.push(`/chat/${topic.mainChatId}`) }
            ], [
              { label: 'Delete', icon: 'i-heroicons-trash', color: 'error', onSelect: () => handleDeleteTopic(topic) }
            ]]"
            :content="{ align: 'end' }"
          >
            <UButton
              color="neutral"
              variant="ghost"
              icon="i-heroicons-ellipsis-vertical"
              size="sm"
              class="text-zinc-400 hover:text-white"
            />
          </UDropdownMenu>
        </div>

      </div>
    </div>

    <!-- Gemini Gems Wide 2-Column Horizontal Modal (Landscape Rectangle) -->
    <UModal
      v-model:open="showSettingsModal"
      :ui="{ content: 'sm:max-w-6xl w-full sm:w-[1120px] rounded-3xl' }"
    >
      <template #content>
        <div v-if="selectedTopic" class="p-8 space-y-6 max-h-[720px] w-full bg-zinc-950 text-zinc-100 rounded-3xl overflow-y-auto border border-zinc-800 shadow-2xl">

          <!-- Back Header & Avatar Title -->
          <div class="flex items-center justify-between pb-5 border-b border-zinc-800">
            <div class="flex items-center gap-3">
              <UButton
                color="neutral"
                variant="ghost"
                icon="i-heroicons-chevron-left"
                size="sm"
                class="rounded-full text-zinc-400 hover:text-white"
                @click="showSettingsModal = false"
              />
              <div class="w-10 h-10 rounded-xl bg-emerald-500/10 text-emerald-400 flex items-center justify-center font-bold text-base shrink-0">
                {{ editedTitle ? editedTitle.slice(0, 1) : 'T' }}
              </div>
              <h2 class="text-xl font-bold text-zinc-100 tracking-tight">{{ editedTitle || 'Topic Settings' }}</h2>
            </div>
            <span class="text-xs text-zinc-500 font-mono">ID: {{ selectedTopic.id.slice(0, 8) }}</span>
          </div>

          <!-- 2-Column Horizontal Grid Container (Strict Side-by-Side Flow) -->
          <div class="grid grid-cols-2 gap-8 items-start">

            <!-- Left Column: 基本信息 & 策略设置 -->
            <div class="space-y-6">
              <!-- Field 1: 标题 (Title) -->
              <div class="space-y-2">
                <label class="text-xs font-semibold text-zinc-300 block">Title</label>
                <UInput
                  v-model="editedTitle"
                  placeholder="Enter topic title..."
                  size="md"
                  class="w-full bg-zinc-900 border-zinc-800 rounded-xl text-sm"
                />
              </div>

              <!-- Field 2: 描述 (Description) -->
              <div class="space-y-2">
                <label class="text-xs font-semibold text-zinc-300 block">Description</label>
                <UTextarea
                  v-model="editedDescription"
                  :rows="3"
                  placeholder="Brief description of this topic workspace purpose and scope..."
                  class="w-full bg-zinc-900 border-zinc-800 rounded-xl text-xs"
                />
              </div>

              <!-- Field 3: 预设工具/加权策略 (Preset Strategy Dropdown) -->
              <div class="space-y-2">
                <div class="flex items-center justify-between">
                  <div class="flex items-center gap-1.5 text-xs font-semibold text-zinc-300">
                    <span>Preset Strategy</span>
                    <UIcon name="i-heroicons-information-circle" class="w-4 h-4 text-zinc-500" />
                  </div>
                  <span class="text-[11px] text-zinc-500">RAG Vector Retrieval Threshold</span>
                </div>

                <USelect
                  v-model="selectedWeightMode"
                  :items="[
                    { label: 'Auto (Smart Retrieval)', value: 'auto' },
                    { label: 'Deeper (Focused & Precise)', value: 'deeper' },
                    { label: 'Wider (Broad Domain Search)', value: 'wider' }
                  ]"
                  size="md"
                  class="w-full bg-zinc-900 border-zinc-800 rounded-xl"
                />
              </div>

              <!-- Hidden File Input -->
              <input
                ref="fileInputRef"
                type="file"
                class="hidden"
                accept=".txt,.md,.pdf,.doc,.docx,.json,.csv"
                @change="handleFileUpload"
              />

              <!-- Field 4: 知识 (Knowledge Upload) -->
              <div class="space-y-2 pt-2">
                <div class="flex items-center gap-1.5">
                  <label class="text-xs font-semibold text-zinc-300">Knowledge</label>
                  <UIcon name="i-heroicons-information-circle" class="w-4 h-4 text-zinc-500" />
                </div>

                <!-- Sleek Minimal File Upload Button -->
                <div
                  class="p-4 bg-zinc-900 hover:bg-zinc-850 border border-zinc-800 rounded-xl flex items-center justify-between cursor-pointer transition-all group"
                  @click="triggerFilePicker"
                >
                  <span class="text-xs text-zinc-400 group-hover:text-zinc-200 transition-colors">
                    {{ uploadingFile ? 'Uploading & parsing document...' : 'Add reference document for topic...' }}
                  </span>
                  <UIcon v-if="!uploadingFile" name="i-heroicons-plus" class="w-5 h-5 text-zinc-400 group-hover:text-white" />
                  <UIcon v-else name="i-heroicons-arrow-path" class="w-5 h-5 text-emerald-400 animate-spin" />
                </div>

                <!-- File List Cards (Horizontal Rectangular Pills) -->
                <div v-if="topicDocs.length" class="flex flex-wrap items-center gap-2 pt-2 max-h-48 overflow-y-auto">
                  <div
                    v-for="doc in topicDocs"
                    :key="doc.docId"
                    class="flex items-center justify-between gap-2 px-3 py-2 bg-zinc-900 hover:bg-zinc-850 border border-zinc-800 hover:border-emerald-500/50 rounded-xl text-xs cursor-pointer transition-all group/doc shrink-0 max-w-full"
                    @click="openSingleDocModal(doc)"
                  >
                    <div class="flex items-center gap-2 truncate min-w-0">
                      <UIcon name="i-heroicons-document-text" class="w-4 h-4 text-emerald-400 shrink-0" />
                      <span class="text-zinc-200 font-medium truncate max-w-[240px]" :title="cleanDocTitle(doc)">{{ cleanDocTitle(doc) }}</span>
                    </div>
                    <UButton
                      color="neutral"
                      variant="ghost"
                      icon="i-heroicons-trash"
                      size="xs"
                      class="text-zinc-500 hover:text-rose-400 opacity-60 group-hover/doc:opacity-100 transition-opacity"
                      @click.stop="handleDeleteDoc(doc.docId)"
                    />
                  </div>
                </div>
              </div>
            </div>

            <!-- Right Column: 指示 (Large Right Column Editor) -->
            <div class="space-y-2 flex flex-col h-full">
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-1.5">
                  <label class="text-xs font-semibold text-zinc-300">Instructions</label>
                  <UIcon name="i-heroicons-information-circle" class="w-4 h-4 text-zinc-500" />
                </div>
                <span class="text-[11px] text-zinc-500 font-mono">System Core Cognition Document</span>
              </div>

              <!-- Tags Row -->
              <div class="p-2.5 bg-zinc-900 border border-zinc-800 rounded-xl flex items-center justify-between gap-2 min-h-[46px]">
                <div class="flex flex-wrap items-center gap-2 flex-1">
                  <!-- Keyword Tags -->
                  <div
                    v-for="(tag, idx) in topicTags"
                    :key="idx"
                    class="inline-flex items-center gap-1.5 px-3 py-1 bg-sky-500/15 hover:bg-sky-500/25 border border-sky-500/30 rounded-lg text-xs font-medium text-sky-300 group/tag transition-all shadow-2xs cursor-default"
                  >
                    <span>{{ tag }}</span>
                    <button
                      type="button"
                      class="text-sky-400/70 hover:text-rose-400 transition-colors focus:outline-none ml-0.5 cursor-pointer"
                      title="Remove tag"
                      @click="removeTag(idx)"
                    >
                      <UIcon name="i-heroicons-x-mark" class="w-3.5 h-3.5" />
                    </button>
                  </div>

                  <!-- Inline Add Tag Input -->
                  <div v-if="isAddingTag" class="flex items-center px-2.5 py-1 bg-sky-950/80 border border-sky-500/50 rounded-lg text-xs w-32 shrink-0">
                    <input
                      ref="tagInputRef"
                      v-model="newTagInput"
                      type="text"
                      placeholder="Add new tag..."
                      class="bg-transparent text-xs text-sky-200 placeholder-sky-400/50 focus:outline-none w-full"
                      @keyup.enter="handleConfirmAddTag"
                      @blur="handleConfirmAddTag"
                    />
                  </div>
                </div>

                <!-- Right Plus Circle Icon Button -->
                <button
                  type="button"
                  class="text-sky-400 hover:text-sky-200 hover:bg-sky-500/20 transition-all p-1 rounded-lg shrink-0 cursor-pointer flex items-center justify-center"
                  title="Add tag"
                  @click="triggerAddTag"
                >
                  <UIcon name="i-heroicons-plus-circle" class="w-5 h-5" />
                </button>
              </div>

              <div class="flex-1 bg-zinc-900 border border-zinc-800 rounded-2xl p-4 flex flex-col min-h-[300px]">
                <UTextarea
                  v-model="localSoul"
                  :rows="12"
                  class="w-full h-full font-mono text-xs border-0 focus:ring-0 bg-transparent leading-relaxed text-zinc-200 resize-none"
                  placeholder="As a domain analysis expert, your goal is to assist users in answering specialized questions under this topic..."
                />
              </div>
            </div>
          </div>




          <!-- Bottom Action Buttons -->
          <div class="flex items-center justify-between pt-6 border-t border-zinc-800">
            <UButton
              color="error"
              variant="ghost"
              size="xs"
              icon="i-heroicons-trash"
              label="Delete Topic"
              class="border border-red-500/30 bg-red-500/10 text-red-400 hover:bg-red-500/20 hover:border-red-500/50 transition-all font-medium rounded-lg px-3 py-1.5"
              @click="handleDeleteTopic(selectedTopic)"
            />
            <div class="flex items-center gap-3">
              <UButton
                color="sky"
                variant="subtle"
                size="sm"
                icon="i-heroicons-sparkles"
                :loading="isSummarizing"
                class="border border-sky-500/40 bg-sky-500/15 text-sky-300 hover:bg-sky-500/25 hover:border-sky-400/60 transition-all font-semibold rounded-lg px-3.5 py-1.5 text-xs shadow-xs"
                @click="handleTriggerSummarize"
              >
                Regenerate
              </UButton>
              <UButton
                color="neutral"
                variant="subtle"
                size="sm"
                class="border border-zinc-700/80 bg-zinc-800/60 text-zinc-300 hover:bg-zinc-700/80 hover:text-white transition-all font-medium rounded-lg px-3.5 py-1.5 text-xs"
                @click="showSettingsModal = false"
              >
                Cancel
              </UButton>
              <UButton
                color="emerald"
                variant="subtle"
                size="sm"
                icon="i-heroicons-check"
                :loading="isSaving"
                class="border border-emerald-500/40 bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25 hover:border-emerald-400/60 transition-all font-semibold rounded-lg px-3.5 py-1.5 text-xs shadow-xs"
                @click="handleSaveSettings"
              >
                Save Changes
              </UButton>
            </div>
          </div>
        </div>
      </template>
    </UModal>

    <!-- Create Topic Modal -->
    <UModal v-model:open="showCreateModal" title="新建话题空间 (Topic Project)">
      <template #content>
        <div class="p-6 space-y-4">
          <div class="space-y-1">
            <label class="text-xs font-semibold text-zinc-300">话题空间名称</label>
            <UInput
              v-model="newTopicTitle"
              placeholder="例如: AI Agent 架构研发 / 业务合规研读..."
              size="sm"
              autofocus
              @keyup.enter="handleCreateTopic"
            />
          </div>

          <div class="flex justify-end gap-2 pt-2">
            <UButton
              color="neutral"
              variant="subtle"
              size="sm"
              class="border border-zinc-700/80 bg-zinc-800/60 text-zinc-300 hover:bg-zinc-700/80 hover:text-white transition-all font-medium rounded-lg px-3.5 py-1.5 text-xs"
              @click="showCreateModal = false"
            >
              Cancel
            </UButton>
            <UButton
              color="emerald"
              variant="subtle"
              size="sm"
              icon="i-heroicons-check"
              :loading="creating"
              :disabled="!newTopicTitle.trim()"
              class="border border-emerald-500/40 bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25 hover:border-emerald-400/60 transition-all font-semibold rounded-lg px-3.5 py-1.5 text-xs shadow-xs"
              @click="handleCreateTopic"
            >
              Create Topic
            </UButton>
          </div>
        </div>
      </template>
    </UModal>

    <!-- Topic Document Pool Viewer Modal (Un-nested for clean close button binding) -->
    <TopicDocumentPool
      v-if="showDocsModal && selectedDocsTopicId"
      v-model:open="showDocsModal"
      :topic-id="selectedDocsTopicId"
    />

    <!-- Single Document Full Text Preview Modal -->
    <DocumentModal
      v-if="showSingleDocModal && selectedDocForModal"
      v-model:open="showSingleDocModal"
      :doc-id="selectedDocForModal.docId"
      :doc-title="cleanDocTitle(selectedDocForModal)"
      :doc-content="selectedDocForModal.content || selectedDocForModal.snippet"
    />
  </div>
</template>


