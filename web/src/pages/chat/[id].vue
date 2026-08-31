<script setup lang="ts">
import { useToast } from '@nuxt/ui/composables'
import { ref, computed, watch, onMounted } from 'vue'
import { $fetch } from 'ofetch'
import { Chat } from '@ai-sdk/vue'
import { DefaultChatTransport } from 'ai'
import type { UIMessage } from 'ai'
import { useModels } from '../../composables/useModels'
import { useChats } from '../../composables/useChats'
import { useCsrf } from '../../composables/useCsrf'
import { useFavorites } from '../../composables/useFavorites'
import { useRoute, useRouter } from 'vue-router'
import ChatMessageContent from '../../components/chat/message/MessageContent.vue'
import ChatMessageActions from '../../components/chat/message/MessageActions.vue'
import ChatVisibility from '../../components/chat/ChatVisibility.vue'
import ChatTitle from '../../components/chat/ChatTitle.vue'
import ChatIndicator from '../../components/chat/Indicator.vue'
import Navbar from '../../components/Navbar.vue'
import SelectionDrawer from '../../components/chat/SelectionDrawer.vue'
import DialogueTreeModal from '../../components/chat/DialogueTreeModal.vue'
import TopicDocumentPool from '../../components/chat/TopicDocumentPool.vue'
import DocumentModal from '../../components/chat/DocumentModal.vue'
import SoulModal from '../../components/chat/SoulModal.vue'
import SuggestionModal from '../../components/chat/SuggestionModal.vue'
import WeightModeSelect from '../../components/chat/WeightModeSelect.vue'
import AttachmentTray from '../../components/chat/AttachmentTray.vue'
import type { Vote } from '../../../server/utils/drizzle'
import { extractAttachmentSelection } from '../../../shared/utils/attachmentParts'
import { knowledgeBaseRetrievalEnabled } from '../../../shared/utils/chatRetrieval'

const route = useRoute<'/chat/[id]'>()
const router = useRouter()
const toast = useToast()
const currentWeightMode = ref<'deeper' | 'auto' | 'wider'>('auto')
const { model } = useModels()
const { fetchChats, chats } = useChats()
const { csrf, headerName } = useCsrf()


const data = await $fetch(`/api/chats/${route.params.id}`).catch((e) => {
  console.error('[chat/[id]] fetch failed:', e)
  return null
})

const isOwner = computed(() => data?.isOwner ?? false)
const visibility = ref<'public' | 'private'>(data?.visibility ?? 'private')
const title = ref<string | null>(data?.title ?? null)

// Topic Space State
const topic = ref<any>(null)
if (data?.topicId) {
  $fetch(`/api/topics/${data.topicId}`).then((t) => {
    topic.value = t
  }).catch(() => {})
}

watch(() => chats.value.find(c => c.id === data?.id)?.label, (label) => {
  if (label && label !== 'Untitled') {
    title.value = label
  }
})

const votes = ref<Vote[]>([])
if (isOwner.value) {
  $fetch(`/api/chats/votes/${route.params.id}`).then((v) => {
    votes.value = v
  }).catch(() => {})
}

const input = ref('')
const attachmentIds = ref<string[]>([])
const acceptedNeedsReviewIds = ref<string[]>([])
const attachmentTray = ref<InstanceType<typeof AttachmentTray> | null>(null)
const latestUserMessage = [...(data?.messages || [])].reverse().find(message => message.role === 'user')
const useKnowledgeBase = ref(knowledgeBaseRetrievalEnabled(
  (latestUserMessage as any)?.metadata,
  (latestUserMessage as any)?.parts,
))

const greeting = computed(() => {
  const hour = new Date().getHours()
  let timeGreeting = 'Good evening'
  if (hour < 12) timeGreeting = 'Good morning'
  else if (hour < 18) timeGreeting = 'Good afternoon'
  return timeGreeting
})

const visibleMessages = computed(() => {
  return chat.messages?.filter(m => m.role === 'user' || m.role === 'assistant') || []
})

const deepResearchMode = ref(false)

const plusMenuItems = computed(() => [[
  {
    label: '上传图片或文件',
    icon: 'i-lucide-paperclip',
    onSelect: () => attachmentTray.value?.open()
  },
  {
    label: '企业知识库检索',
    icon: useKnowledgeBase.value ? 'i-lucide-database-zap' : 'i-lucide-database',
    onSelect: () => { useKnowledgeBase.value = !useKnowledgeBase.value }
  },
  {
    label: deepResearchMode.value ? 'Deep Research: ON' : 'Deep Research',
    icon: 'i-lucide-telescope',
    onSelect: () => { deepResearchMode.value = !deepResearchMode.value }
  }
]])


const chat = new Chat({
  id: data?.id,
  messages: data?.messages,
  transport: new DefaultChatTransport({
    api: `/api/chats/${data?.id}`,
    headers: { [headerName]: csrf() },
    body: { model: model.value },
  }),
  onData: (dataPart) => {
    if (dataPart.type === 'data-chat-title') {
      fetchChats()
    }
  },
  onError(error) {
    let message = error.message
    if (typeof message === 'string' && message[0] === '{') {
      try {
        message = JSON.parse(message).message || message
      } catch {
        // keep original message on malformed JSON
      }
    }
    toast.add({
      description: message,
      icon: 'i-lucide-alert-circle',
      color: 'error',
      duration: 0,
    })
  },
})

function handleSubmit(e: Event) {
  e.preventDefault()
  if (attachmentTray.value?.hasBlockingAttachments()) {
    toast.add({
      description: '请等待附件解析完成；低置信度附件需要确认后才能发送。',
      icon: 'i-lucide-alert-circle',
      color: 'warning',
    })
    return
  }
  if (input.value.trim() || attachmentIds.value.length) {
    const text = input.value.trim() || '请分析这些附件'
    chat.sendMessage({
      text,
      metadata: {
        attachmentIds: attachmentIds.value,
        acceptedNeedsReviewIds: acceptedNeedsReviewIds.value,
        knowledgeBaseRetrievalEnabled: useKnowledgeBase.value,
      },
    } as any)
    input.value = ''
    attachmentTray.value?.resetAfterSend()
    attachmentIds.value = []
    acceptedNeedsReviewIds.value = []
  }
}

const editingMessageId = ref<string | null>(null)

function startEdit(message: UIMessage) {
  if (editingMessageId.value) return
  editingMessageId.value = message.id
}

function cancelEdit() {
  editingMessageId.value = null
}

async function saveEdit(message: UIMessage, text: string) {
  try {
    await $fetch(`/api/chats/messages/${data!.id}`, {
      method: 'DELETE',
      headers: { [headerName]: csrf() },
      body: { messageId: message.id, type: 'edit' },
    })
  } catch {
    toast.add({
      description: 'Failed to update message',
      icon: 'i-lucide-alert-circle',
      color: 'error',
    })
    return
  }

  editingMessageId.value = null
  const retained = extractAttachmentSelection(message.parts, (message as any).metadata)
  chat.sendMessage({
    text,
    messageId: message.id,
    metadata: {
      attachmentIds: retained.attachmentIds,
      acceptedNeedsReviewIds: retained.acceptedNeedsReviewIds,
      knowledgeBaseRetrievalEnabled: knowledgeBaseRetrievalEnabled(
        (message as any).metadata,
        message.parts,
      ),
    },
  } as any)
}

async function regenerateMessage(message: UIMessage) {
  try {
    await $fetch(`/api/chats/messages/${data!.id}`, {
      method: 'DELETE',
      headers: { [headerName]: csrf() },
      body: { messageId: message.id, type: 'regenerate' },
    })
  } catch {
    toast.add({
      description: 'Failed to regenerate message',
      icon: 'i-lucide-alert-circle',
      color: 'error',
    })
    return
  }

  chat.regenerate({ messageId: message.id })
}

function getVote(messageId: string) {
  const vote = votes.value.find(v => v.messageId === messageId)
  if (!vote) return null
  return !!vote.isUpvoted
}

async function vote(message: UIMessage, isUpvoted: boolean) {
  const snapshot = votes.value.map(v => ({ ...v }))
  const toggling = getVote(message.id) === isUpvoted
  const next = toggling ? null : isUpvoted

  votes.value = next === null
    ? votes.value.filter(v => v.messageId !== message.id)
    : [
        ...votes.value.filter(v => v.messageId !== message.id),
        { chatId: data!.id, messageId: message.id, isUpvoted: next },
      ]

  // Prompt user for improvement input when thumbs down is clicked
  if (next === false) {
    suggestMessageId.value = message.id
    showSuggestionModal.value = true
  }


  try {
    await $fetch(`/api/chats/votes/${data!.id}`, {
      method: 'POST',
      headers: { [headerName]: csrf() },
      body: next === null ? { messageId: message.id } : { messageId: message.id, isUpvoted: next },
    })
  } catch {
    votes.value = snapshot
    toast.add({
      description: 'Failed to save vote',
      icon: 'i-lucide-alert-circle',
      color: 'error',
    })
  }
}

// === Topic & Branch Features ===
const showSelectionDrawer = ref(false)
const selectedText = ref('')
const selectedContextText = ref('')
const floatAskPos = ref<{ x: number; y: number } | null>(null)

const showDialogueTree = ref(false)
const showDocumentPool = ref(false)
const showDocumentModal = ref(false)
const previewDocId = ref('')
const showSoulModal = ref(false)

const showSuggestionModal = ref(false)
const suggestMessageId = ref('')

function handleTextSelection() {
  setTimeout(() => {
    const selection = window.getSelection()
    const text = selection?.toString().trim()
    if (text && text.length > 1) {
      selectedText.value = text
      
      // Traverse up DOM to extract full parent message text
      let fullMessageText = ''
      let node: Node | null = selection?.anchorNode || null
      while (node && node !== document.body) {
        if (node instanceof HTMLElement) {
          if (
            node.classList.contains('chat-message-content') ||
            node.getAttribute('data-role') ||
            node.querySelector('.whitespace-pre-wrap') ||
            node.querySelector('.chat-comark')
          ) {
            fullMessageText = node.innerText
            break
          }
        }
        node = node.parentNode
      }

      if (!fullMessageText && selection?.anchorNode?.parentElement) {
        let parent: HTMLElement | null = selection.anchorNode.parentElement
        while (parent && parent !== document.body && parent.innerText.length < 10000) {
          if (parent.tagName === 'DIV' || parent.tagName === 'ARTICLE' || parent.tagName === 'SECTION') {
            fullMessageText = parent.innerText
            break
          }
          parent = parent.parentElement
        }
      }

      selectedContextText.value = (fullMessageText || selection?.anchorNode?.parentElement?.innerText || text).trim()

      const range = selection?.getRangeAt(0)
      const rect = range?.getBoundingClientRect()
      if (rect && rect.width > 0) {
        floatAskPos.value = {
          x: rect.left + rect.width / 2,
          y: rect.top - 10
        }
      }
    } else {
      floatAskPos.value = null
    }
  }, 20)
}

function copySelectedText() {
  if (selectedText.value) {
    navigator.clipboard.writeText(selectedText.value)
    floatAskPos.value = null
    window.getSelection()?.removeAllRanges()
    toast.add({ title: '已复制划选文本', color: 'success' })
  }
}

function openSelectionDrawer() {
  showSelectionDrawer.value = true
  floatAskPos.value = null
  window.getSelection()?.removeAllRanges()
}



async function handleUpdateWeightMode(mode: 'deeper' | 'auto' | 'wider') {
  if (!topic.value?.id) return
  try {
    const updated: any = await $fetch(`/api/topics/${topic.value.id}`, {
      method: 'PATCH',
      headers: { [headerName]: csrf() },
      body: { weightMode: mode }
    })
    topic.value = updated
    toast.add({
      title: '检索加权模式已切换',
      description: `当前模式: ${mode.toUpperCase()}`,
      color: 'success'
    })
  } catch (err: any) {
    toast.add({ description: err.message, color: 'error' })
  }
}

async function handleSaveSoul(newSoul: string) {
  if (!topic.value?.id) return
  try {
    const updated: any = await $fetch(`/api/topics/${topic.value.id}`, {
      method: 'PATCH',
      headers: { [headerName]: csrf() },
      body: { soulContent: newSoul }
    })
    topic.value = updated
    toast.add({ title: 'Soul.md 认知记忆修正成功', color: 'success' })
  } catch (err: any) {
    toast.add({ description: err.message, color: 'error' })
  }
}

const { notifyFavoriteChanged } = useFavorites()

async function handleFavoriteMessage(message: UIMessage, isFav: boolean) {
  try {
    await $fetch(`/api/messages/${message.id}/feedback`, {
      method: 'POST',
      headers: { [headerName]: csrf() },
      body: { isFavorite: isFav }
    })
    if (isFav) {
      toast.add({ title: 'Saved to Favorites', color: 'success' })
    }
    // Notify layout sidebar to refresh favorites list immediately
    notifyFavoriteChanged()
  } catch (e) {
    console.error('Favorite error:', e)
  }
}


function openSuggestModal(message: UIMessage) {
  suggestMessageId.value = message.id
  showSuggestionModal.value = true
}

function handlePreviewDoc(docId: string) {
  previewDocId.value = docId
  showDocumentPool.value = false
  showDocumentModal.value = true
}

function handleSelectChatFromTree(chatId: string) {
  showDialogueTree.value = false
  if (chatId !== data?.id) {
    router.push(`/chat/${chatId}`)
  }
}

function handleGlobalMouseDown(e: MouseEvent) {
  const target = e.target as HTMLElement
  // Don't dismiss if clicking inside the pill
  if (target && target.closest('.float-selection-pill')) return
  // Don't dismiss if there is still a selection (e.g. mousedown on selected text itself)
  const text = window.getSelection()?.toString().trim()
  if (text && text.length > 1) return

  floatAskPos.value = null
}

onMounted(() => {
  document.addEventListener('mousedown', handleGlobalMouseDown)

  if (isOwner.value && data?.messages?.length === 1 && data.messages[0]?.role === 'user') {
    chat.regenerate()
  }
})
</script>

<template>
  <UDashboardPanel
    v-if="data?.id"
    id="chat"
    class="relative min-h-0"
    :ui="{ body: 'p-0 sm:p-0 overscroll-none' }"
    @mouseup="handleTextSelection"
  >
    <template #header>
      <div class="flex flex-col w-full">
        <Navbar>
          <template #title>
            <ChatTitle
              :chat-id="data!.id"
              :title="title"
              :is-owner="isOwner"
              @update:title="title = $event"
            />
          </template>

          <ChatVisibility
            v-if="isOwner"
            :chat-id="data!.id"
            :visibility="visibility"
            @update:visibility="visibility = $event"
          />
        </Navbar>
      </div>
    </template>

    <template #body>
      <div class="flex-1 flex flex-row min-h-0 relative overflow-hidden w-full h-full">
        <!-- Main Chat Area (Left Panel) -->
        <div class="flex-1 flex flex-col min-w-0 h-full overflow-y-auto relative">
          <!-- Empty Chat / Branch New Chat Landing View -->
          <UContainer v-if="!visibleMessages.length" class="flex-1 flex flex-col justify-center gap-4 sm:gap-6 py-8 min-h-[75vh]">
            <h1 class="text-3xl sm:text-4xl text-highlighted font-bold">
              {{ greeting }}
            </h1>

            <UChatPrompt
              v-if="isOwner"
              v-model="input"
              :error="chat.error"
              :status="chat.status === 'streaming' ? 'streaming' : 'ready'"
              placeholder="Ask me anything..."
              variant="subtle"
              class="rounded-2xl shadow-lg"
              :ui="{ base: 'px-1.5' }"
              @submit="handleSubmit"
            >
              <template #footer>
                <AttachmentTray
                  ref="attachmentTray"
                  scope="chat"
                  :chat-id="data?.id"
                  :topic-id="topic?.id"
                  :disabled="chat.status === 'streaming'"
                  @change="(ids, reviewed) => { attachmentIds = ids; acceptedNeedsReviewIds = reviewed }"
                />
                <!-- + Menu: Attachments / Knowledge Base / Deep Research -->
                <UDropdownMenu :items="plusMenuItems" :content="{ align: 'start' }">
                  <UButton
                    color="neutral"
                    variant="ghost"
                    size="sm"
                    icon="i-lucide-plus"
                    aria-label="打开更多功能"
                    :class="['rounded-full cursor-pointer transition-transform', deepResearchMode ? 'text-emerald-400 rotate-45' : 'text-zinc-400 hover:text-zinc-100']"
                  />
                </UDropdownMenu>

                <span v-if="useKnowledgeBase" class="text-xs font-semibold text-primary bg-primary/10 px-2 py-0.5 rounded-full">企业知识库检索</span>

                <!-- Deep Research Indicator Badge -->
                <span v-if="deepResearchMode" class="text-xs font-semibold text-emerald-400 bg-emerald-400/10 px-2 py-0.5 rounded-full">Deep Research</span>

                <!-- Right: WeightMode + Submit -->
                <div class="ms-auto flex items-center gap-1">
                  <WeightModeSelect
                    :model-value="topic?.weightMode || currentWeightMode"
                    @change="handleUpdateWeightMode"
                  />
                  <UChatPromptSubmit
                    :status="chat.status === 'streaming' ? 'streaming' : 'ready'"
                    color="neutral"
                    size="sm"
                    class="cursor-pointer"
                    @stop="chat.stop()"
                    @reload="chat.regenerate()"
                  />
                </div>
              </template>
            </UChatPrompt>

          </UContainer>

          <!-- Active Chat Messages View -->
          <UContainer v-else class="flex-1 flex flex-col gap-4 sm:gap-6 relative" @mouseup="handleTextSelection">

            <UChatMessages
              should-auto-scroll
              :messages="chat.messages"
              :status="chat.status"
              :spacing-offset="isOwner ? 160 : 0"
              class="pt-(--ui-header-height) pb-4 sm:pb-6"
            >
              <template #indicator>
                <div class="flex items-center gap-1.5">
                  <ChatIndicator />
                  <UChatShimmer text="Thinking..." class="text-sm" />
                </div>
              </template>

              <template #content="{ message }">
                <ChatMessageContent
                  :message="message"
                  :editing="isOwner && editingMessageId === message.id"
                  @save="saveEdit"
                  @cancel-edit="cancelEdit"
                />
              </template>

              <template
                v-if="isOwner"
                #actions="{ message }"
              >
                <ChatMessageActions
                  :message="{ ...message, isFavorite: (message as any).isFavorite ?? false }"
                  :streaming="chat.status === 'streaming' && message.id === chat.messages[chat.messages.length - 1]?.id"
                  :editing="editingMessageId === message.id"
                  :vote="getVote(message.id)"
                  @edit="startEdit"
                  @regenerate="regenerateMessage"
                  @vote="vote"
                  @favorite="handleFavoriteMessage"
                  @suggest="openSuggestModal"
                />
              </template>
            </UChatMessages>

            <!-- Sleek Floating Selection Tooltip -->
            <div
              v-if="floatAskPos && selectedText"
              class="float-selection-pill fixed z-50 -translate-x-1/2 -translate-y-full mb-2.5 flex items-center gap-1 p-1 rounded-full bg-zinc-900/90 dark:bg-zinc-800/90 text-white shadow-2xl backdrop-blur-md border border-zinc-700/60 select-none animate-in fade-in zoom-in-95 duration-150 pointer-events-auto"
              :style="{ left: floatAskPos.x + 'px', top: floatAskPos.y + 'px' }"
              @pointerdown.stop
            >
              <button
                type="button"
                class="rounded-full text-zinc-300 hover:text-white hover:bg-zinc-700/60 cursor-pointer px-2.5 py-1 text-xs font-medium flex items-center gap-1.5 transition-colors"
                @pointerdown.stop="copySelectedText"
              >
                <UIcon name="i-lucide-copy" class="w-3.5 h-3.5 text-zinc-400" />
                <span>复制</span>
              </button>
              <div class="w-px h-3.5 bg-zinc-700/60" />
              <button
                type="button"
                class="rounded-full text-zinc-200 hover:text-white hover:bg-zinc-700/60 cursor-pointer px-2.5 py-1 text-xs font-medium flex items-center gap-1.5 transition-colors"
                @pointerdown.stop="openSelectionDrawer"
              >
                <UIcon name="i-heroicons-sparkles" class="w-3.5 h-3.5 text-amber-400" />
                <span>划词提问</span>
              </button>
            </div>

            <UChatPrompt
              v-if="isOwner"
              v-model="input"
              :error="chat.error"
              :status="chat.status === 'streaming' ? 'streaming' : 'ready'"
              placeholder="Ask me anything..."
              variant="subtle"
              class="sticky bottom-6 mb-6 [view-transition-name:chat-prompt] rounded-2xl shadow-lg z-10"
              :ui="{ base: 'px-1.5' }"
              @submit="handleSubmit"
            >
              <template #footer>
                <AttachmentTray
                  ref="attachmentTray"
                  scope="chat"
                  :chat-id="data?.id"
                  :topic-id="topic?.id"
                  :disabled="chat.status === 'streaming'"
                  @change="(ids, reviewed) => { attachmentIds = ids; acceptedNeedsReviewIds = reviewed }"
                />
                <!-- + Menu: Attachments / Knowledge Base / Deep Research -->
                <UDropdownMenu :items="plusMenuItems" :content="{ align: 'start' }">
                  <UButton
                    color="neutral"
                    variant="ghost"
                    size="sm"
                    icon="i-lucide-plus"
                    aria-label="打开更多功能"
                    :class="['rounded-full cursor-pointer transition-transform', deepResearchMode ? 'text-emerald-400 rotate-45' : 'text-zinc-400 hover:text-zinc-100']"
                  />
                </UDropdownMenu>

                <span v-if="useKnowledgeBase" class="text-xs font-semibold text-primary bg-primary/10 px-2 py-0.5 rounded-full">企业知识库检索</span>

                <!-- Deep Research Indicator Badge -->
                <span v-if="deepResearchMode" class="text-xs font-semibold text-emerald-400 bg-emerald-400/10 px-2 py-0.5 rounded-full">Deep Research</span>

                <!-- Right: WeightMode + Submit -->
                <div class="ms-auto flex items-center gap-1">
                  <WeightModeSelect
                    :model-value="topic?.weightMode || currentWeightMode"
                    @change="handleUpdateWeightMode"
                  />
                  <UChatPromptSubmit
                    :status="chat.status === 'streaming' ? 'streaming' : 'ready'"
                    color="neutral"
                    size="sm"
                    class="cursor-pointer"
                    @stop="chat.stop()"
                    @reload="chat.regenerate()"
                  />
                </div>
              </template>
            </UChatPrompt>

          </UContainer>
        </div>

        <!-- In-Flow Right Side Panel for Selection Q&A (Same plane layout, non-overlay) -->
        <SelectionDrawer
          v-if="showSelectionDrawer"
          :open="showSelectionDrawer"
          :selected-text="selectedText"
          :context-text="selectedContextText"
          :chat-id="data!.id"
          :topic-id="topic?.id"
          @update:open="showSelectionDrawer = $event"
        />
      </div>
    </template>
  </UDashboardPanel>

  <DialogueTreeModal
    v-if="topic && showDialogueTree"
    :open="showDialogueTree"
    :topic-id="topic.id"
    :current-chat-id="data!.id"
    @update:open="showDialogueTree = $event"
    @select-chat="handleSelectChatFromTree"
  />

  <TopicDocumentPool
    v-if="topic && showDocumentPool"
    :open="showDocumentPool"
    :topic-id="topic.id"
    @update:open="showDocumentPool = $event"
    @preview-doc="handlePreviewDoc"
  />

  <DocumentModal
    v-if="showDocumentModal"
    :open="showDocumentModal"
    :doc-id="previewDocId"
    @update:open="showDocumentModal = $event"
    @ask-selected-text="(txt, ctx) => { selectedText = txt; selectedContextText = ctx; showSelectionDrawer = true; showDocumentModal = false; }"
  />

  <SoulModal
    v-if="topic && showSoulModal"
    :open="showSoulModal"
    :topic-id="topic.id"
    :soul-content="topic.soulContent"
    @update:open="showSoulModal = $event"
    @save-soul="handleSaveSoul"
  />

  <SuggestionModal
    v-if="showSuggestionModal"
    :open="showSuggestionModal"
    :message-id="suggestMessageId"
    @update:open="showSuggestionModal = $event"
    @submit="toast.add({ title: '改进建议已成功提交并存入 Soul', color: 'success' })"
  />

</template>
