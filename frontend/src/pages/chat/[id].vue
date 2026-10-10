<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount, provide } from 'vue'
import { useTextareaAutosize } from '@vueuse/core'
import { $fetch } from 'ofetch'
import { Chat } from '@ai-sdk/vue'
import { DefaultChatTransport } from 'ai'
import type { UIMessage } from 'ai'
import { useToast } from '@nuxt/ui/composables'
import { useModels } from '../../composables/useModels'
import { useChats } from '../../composables/useChats'
import { useCsrf } from '../../composables/useCsrf'
import { useFavorites } from '../../composables/useFavorites'
import { useSessionFacts } from '../../composables/useSessionFacts'
import { useUserSession } from '../../composables/useUserSession'
import { useRoute, useRouter } from 'vue-router'
import ChatMessageContent from '../../components/chat/message/MessageContent.vue'
import ChatMessageActions from '../../components/chat/message/MessageActions.vue'
import ChatVisibility from '../../components/chat/ChatVisibility.vue'
import ChatTitle from '../../components/chat/ChatTitle.vue'
import Navbar from '../../components/Navbar.vue'
import SelectionDrawer from '../../components/chat/SelectionDrawer.vue'
import DialogueTreeModal from '../../components/chat/DialogueTreeModal.vue'
import TopicDocumentPool from '../../components/chat/TopicDocumentPool.vue'
import DocumentModal from '../../components/chat/DocumentModal.vue'
import SoulModal from '../../components/chat/SoulModal.vue'
import SuggestionModal from '../../components/chat/SuggestionModal.vue'
import CascadingModeSelector from '../../components/chat/CascadingModeSelector.vue'
import AttachmentTray from '../../components/chat/AttachmentTray.vue'
import FactProposalCard from '../../components/chat/memory/FactProposalCard.vue'
import SessionFactPanel from '../../components/chat/memory/SessionFactPanel.vue'
import QuickNavDial from '../../components/chat/QuickNavDial.vue'
import HitRateDrawer from '../../components/chat/HitRateDrawer.vue'
import ProgressIndicator from '../../components/chat/ProgressIndicator.vue'
import ReasoningFloatingWindow from '../../components/chat/ReasoningFloatingWindow.vue'
import ResearchModeNotice from '../../components/research/ResearchModeNotice.vue'
import { useResearchLaunch } from '../../composables/useResearchLaunch'
import type { Vote } from '../../../server/utils/drizzle'
import type { FactCategory } from '../../types/memory'
import { extractAttachmentSelection } from '../../../shared/utils/attachmentParts'
import { knowledgeBaseRetrievalEnabled } from '../../../shared/utils/chatRetrieval'
import { chatExplorationMode } from '../../../shared/utils/chatExploration'

const route = useRoute<'/chat/[id]'>()
const router = useRouter()
const toast = useToast()
const showHitRateDrawer = ref(false)
const isWeightModeSaving = ref(false)
const selectedResearchDocumentIds = ref<string[]>([])
const { launchResearch, launchingResearch, researchLaunchError } = useResearchLaunch()

const currentWeightMode = ref<'thinking' | 'auto' | 'fast'>('fast')

const { model } = useModels()
const { fetchChats, chats } = useChats()
const { csrf, headerName } = useCsrf()
const { loggedIn } = useUserSession()
const sessionFacts = useSessionFacts()
const memoryRecallMessageIds = ref<string[]>([])
const hasPendingTrustedMemoryRecall = ref(false)
const {
  available: sessionFactsAvailable,
  loading: sessionFactsLoading,
  proposedFacts,
  confirmedFacts
} = sessionFacts


const data = await $fetch(`/api/chats/${route.params.id}`).catch((e) => {
  console.error('[chat/[id]] fetch failed:', e)
  return null
})
if (data?.weightMode === 'fast' || data?.weightMode === 'auto' || data?.weightMode === 'thinking') {
  currentWeightMode.value = data.weightMode
}

const isOwner = computed(() => data?.isOwner ?? false)
const visibility = ref<'public' | 'private'>(data?.visibility ?? 'private')
const title = ref<string | null>(data?.title ?? null)
const activeChatId = computed(() => typeof route.params.id === 'string' ? route.params.id : data?.id ?? '')
const sessionFactsAllowed = computed(() => Boolean(
  activeChatId.value
  && isOwner.value
  && visibility.value === 'private'
  && loggedIn.value
))

function isMemoryRecallMessage(messageId: string): boolean {
  return memoryRecallMessageIds.value.includes(messageId)
}

async function refreshSessionFacts(showFailure = false) {
  const chatId = activeChatId.value
  if (!sessionFactsAllowed.value || !chatId) {
    sessionFacts.clear()
    return
  }
  const result = await sessionFacts.load(chatId)
  if (showFailure && result === 'failed') {
    toast.add({ description: 'Failed to update memory', icon: 'i-lucide-alert-circle', color: 'error' })
  }
}

watch([() => route.params.id, sessionFactsAllowed], () => {
  if (sessionFactsAllowed.value && activeChatId.value) {
    sessionFacts.activate(activeChatId.value)
  } else {
    sessionFacts.clear()
  }
  void refreshSessionFacts(true)
}, { immediate: true })

function showSessionFactsResult(result: { ok: boolean, code?: 'fact_sensitive' | 'operation_failed' }) {
  if ('discarded' in result && result.discarded) return
  if (result.ok) return
  toast.add({
    description: result.code === 'fact_sensitive' ? 'This content is sensitive and cannot be saved as memory' : 'Memory operation failed',
    icon: 'i-lucide-alert-circle',
    color: 'error'
  })
}

async function saveMessageAsFact(message: UIMessage, category: FactCategory) {
  if (!activeChatId.value || message.role !== 'user' || !sessionFactsAllowed.value) return
  showSessionFactsResult(await sessionFacts.propose(activeChatId.value, message.id, category))
}

async function confirmFact(factId: string) {
  if (!activeChatId.value || !sessionFactsAllowed.value) return
  showSessionFactsResult(await sessionFacts.confirm(activeChatId.value, factId))
}

async function revokeFact(factId: string) {
  if (!activeChatId.value || !sessionFactsAllowed.value) return
  showSessionFactsResult(await sessionFacts.revoke(activeChatId.value, factId))
}


// Topic Space State
const topic = ref<any>(null)
if (data?.topicId) {
  $fetch(`/api/topics/${data.topicId}`).then((t: any) => {
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

const { textarea: textareaRef, input } = useTextareaAutosize({ input: '' })
const isComposing = ref(false)

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !isComposing.value) {
    e.preventDefault()
    if (!input.value?.trim() && !attachmentIds.value.length) {
      input.value = ''
      return
    }
    handleSubmit(e)
  }
}

function onBlur() {
  if (!input.value?.trim()) {
    input.value = ''
  }
}

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

const deepResearchMode = ref(chatExplorationMode(
  (latestUserMessage as any)?.metadata,
  (latestUserMessage as any)?.parts,
) === 'force')
const plusMenuItems = computed(() => [
  [
    {
      label: 'Attach Files',
      icon: 'i-lucide-paperclip',
      onSelect: () => attachmentTray.value?.open()
    },
    {
      label: 'Deep Research',
      icon: 'i-lucide-telescope',
      type: 'checkbox' as const,
      checked: deepResearchMode.value,
      onSelect: () => { deepResearchMode.value = !deepResearchMode.value }
    }
  ]
])



const chat = new Chat({
  id: data?.id,
  messages: data?.messages,
  transport: new DefaultChatTransport({
    api: `/api/chats/${data?.id}`,
    headers: { [headerName]: csrf() },
    body: {
      get model() { return model.value },
    },
  }),
  onData: (dataPart) => {
    if (dataPart.type === 'data-chat-title') {
      fetchChats()
    }
    if (dataPart.type === 'data-memory-recall') {
      // The server-generated persistence ID is not necessarily the ID created
      // by the client streaming state. Associate this trusted marker only when
      // Chat provides the completed assistant message below.
      hasPendingTrustedMemoryRecall.value = true
    }
  },
  onFinish: ({ message, isAbort, isDisconnect, isError }) => {
    if (hasPendingTrustedMemoryRecall.value && !isAbort && !isDisconnect && !isError && message.role === 'assistant') {
      if (!memoryRecallMessageIds.value.includes(message.id)) {
        memoryRecallMessageIds.value = [...memoryRecallMessageIds.value, message.id]
      }
    }
    hasPendingTrustedMemoryRecall.value = false
    if (!isAbort && !isDisconnect && !isError) {
      void refreshSessionFacts(true)
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

provide('is-chat-streaming', computed(() => chat.status === 'streaming'))

void textareaRef

const activeReasoningMessage = computed<UIMessage | null>(() => {
  const assistantMessages = chat.messages.filter(m => m.role === 'assistant')
  return assistantMessages.length > 0 ? (assistantMessages[assistantMessages.length - 1] ?? null) : null
})

async function handleSubmit(e: Event) {
  e.preventDefault()
  if (deepResearchMode.value) {
    if (input.value.trim()) {
      const launched = await launchResearch(input.value.trim(), selectedResearchDocumentIds.value)
      if (launched) input.value = ''
    }
    return
  }
  if (isWeightModeSaving.value || chat.status === 'streaming') return
  if (attachmentTray.value?.hasBlockingAttachments()) {
    toast.add({
      description: 'Please wait for attachments to finish processing; low confidence items require confirmation before sending.',
      icon: 'i-lucide-alert-circle',
      color: 'warning',
    })
    return
  }
  if (input.value.trim() || attachmentIds.value.length) {
    const text = input.value.trim() || 'Please analyze these attachments'
    chat.sendMessage({
      text,
      metadata: {
        attachmentIds: attachmentIds.value,
        acceptedNeedsReviewIds: acceptedNeedsReviewIds.value,
        knowledgeBaseRetrievalEnabled: useKnowledgeBase.value,
        explorationMode: deepResearchMode.value ? 'force' : 'auto',
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
  if (isWeightModeSaving.value || chat.status === 'streaming') return
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
  if (isWeightModeSaving.value || chat.status === 'streaming') return
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
    toast.add({ title: 'Selected text copied to clipboard', color: 'success' })
  }
}

function openSelectionDrawer() {
  showSelectionDrawer.value = true
  floatAskPos.value = null
  window.getSelection()?.removeAllRanges()
}



async function handleUpdateWeightMode(mode: 'thinking' | 'auto' | 'fast') {
  if (isWeightModeSaving.value || mode === currentWeightMode.value) return
  const previousMode = currentWeightMode.value
  currentWeightMode.value = mode
  isWeightModeSaving.value = true
  try {
    await $fetch(`/api/chats/${activeChatId.value}/mode`, {
      method: 'PATCH',
      headers: { [headerName]: csrf() },
      body: { weightMode: mode }
    })
  } catch (err: any) {
    currentWeightMode.value = previousMode
    toast.add({ description: 'Failed to save chat mode', icon: 'i-lucide-alert-circle', color: 'error' })
    console.warn('Failed to save chat weight mode:', err)
  } finally {
    isWeightModeSaving.value = false
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
    toast.add({ title: 'Soul.md memory updated successfully', color: 'success' })
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

onBeforeUnmount(() => {
  sessionFacts.clear()
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

          <template #right-end>
            <!-- Hit Rate Monitor Button at the absolute far right top navbar (Solid White Icon) -->
            <UButton
              color="neutral"
              variant="ghost"
              icon="i-lucide-bar-chart-3"
              size="sm"
              title="Hit Rate Monitoring"
              :class="[
                'cursor-pointer transition-colors text-zinc-100 dark:text-white',
                showHitRateDrawer ? 'bg-zinc-800 text-emerald-400 font-bold' : 'hover:text-white hover:bg-zinc-800/80'
              ]"
              @click="showHitRateDrawer = !showHitRateDrawer"
            />
          </template>
        </Navbar>
      </div>
    </template>

    <template #body>
      <div class="flex-1 flex flex-row min-h-0 relative overflow-hidden w-full h-full">
        <!-- Main Chat Area (Left Panel) -->
        <div class="flex-1 flex flex-col min-w-0 h-full overflow-y-auto relative">
          <!-- Top-Right Floating Reasoning Window -->
          <ReasoningFloatingWindow
            :message="activeReasoningMessage"
            :status="launchingResearch ? 'streaming' : chat.status"
          />

          <!-- Empty Chat / Branch New Chat Landing View -->
          <div v-if="!visibleMessages.length" class="flex-1 flex flex-col items-center justify-center px-4 sm:px-6 w-full h-full min-h-0">
            <div class="w-full max-w-3xl sm:max-w-4xl flex flex-col items-center gap-8">
              <!-- Hero Title in Literata -->
              <h1 class="text-3xl sm:text-4xl text-highlighted font-medium font-display tracking-tight select-none">
                {{ greeting }}
              </h1>

              <!-- Prompt Box Capsule (Single Inline Pill style matching ChatGPT) -->
              <div class="w-full">
                <div
                  v-if="isOwner"
                  class="w-full rounded-[30px] sm:rounded-[34px] border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-[0_6px_30px_-6px_rgba(0,0,0,0.08)] dark:shadow-[0_6px_30px_-6px_rgba(0,0,0,0.4)] hover:border-zinc-300 dark:hover:border-zinc-700 focus-within:border-zinc-400 dark:focus-within:border-zinc-600 focus-within:shadow-[0_10px_38px_-6px_rgba(0,0,0,0.12)] dark:focus-within:shadow-[0_10px_38px_-6px_rgba(0,0,0,0.5)] transition-all duration-200 px-4 py-2.5 sm:px-5 sm:py-3.5 flex flex-col gap-2.5 min-h-[58px] sm:min-h-[64px]"
                >
                  <!-- Attachment Tray (if attachments selected) -->
                  <AttachmentTray
                    ref="attachmentTray"
                    scope="chat"
                    :chat-id="data?.id"
                    :topic-id="topic?.id"
                    hide-trigger
                    :disabled="chat.status === 'streaming'"
                    @change="(ids, reviewed) => { attachmentIds = ids; acceptedNeedsReviewIds = reviewed }"
                  />

                  <!-- Input Row: [+]  [Input Area]  [🧠 Mode] [^] -->
                  <div class="flex items-center gap-2.5 sm:gap-3 w-full">
                    <!-- Left: + Menu Button (Inline with text) -->
                    <div class="flex items-center shrink-0">
                      <UDropdownMenu
                        :items="plusMenuItems"
                        :content="{ align: 'start', sideOffset: 8 }"
                        :ui="{
                          content: 'min-w-44 p-1.5 rounded-2xl bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl border border-zinc-200/80 dark:border-zinc-800/80 shadow-[0_12px_36px_-6px_rgba(0,0,0,0.12)] dark:shadow-[0_12px_36px_-6px_rgba(0,0,0,0.6)] ring-0',
                          group: 'p-0 flex flex-col gap-1',
                          item: 'rounded-xl px-3 py-2 text-xs sm:text-sm font-medium transition-all duration-150 cursor-pointer text-zinc-700 dark:text-zinc-200 hover:text-zinc-900 dark:hover:text-white hover:bg-zinc-100 dark:hover:bg-zinc-800 active:scale-[0.98] select-none flex items-center gap-2.5 data-highlighted:bg-zinc-100 dark:data-highlighted:bg-zinc-800',
                          itemLeadingIcon: 'w-4 h-4 text-zinc-500 dark:text-zinc-400 group-hover:text-zinc-900 dark:group-hover:text-zinc-100 transition-colors',
                          itemTrailing: 'ml-auto flex items-center',
                          itemTrailingIcon: 'w-4 h-4 text-emerald-500 dark:text-emerald-400'
                        }"
                      >
                        <button
                          type="button"
                          aria-label="Add attachments & options"
                          title="Add attachments & options"
                          class="rounded-xl text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800/80 transition-all cursor-pointer w-9 h-9 sm:w-9.5 sm:h-9.5 flex items-center justify-center p-0 shrink-0 active:scale-95"
                        >
                          <UIcon name="i-lucide-plus" class="w-5 h-5 sm:w-5.5 sm:h-5.5" />
                        </button>
                      </UDropdownMenu>
                    </div>

                    <!-- Deep Research badge (only visible when active) -->
                    <span
                      v-if="deepResearchMode"
                      class="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-500 dark:text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-1 rounded-full whitespace-nowrap select-none shrink-0"
                    >
                      <UIcon name="i-lucide-telescope" class="w-3.5 h-3.5" />
                      <span>Deep Research</span>
                      <button
                        type="button"
                        class="hover:bg-emerald-500/20 rounded-full p-0.5 ml-0.5 cursor-pointer inline-flex items-center transition-colors"
                        title="Disable Deep Research"
                        @click.stop="deepResearchMode = false"
                      >
                        <UIcon name="i-lucide-x" class="w-3 h-3" />
                      </button>
                    </span>

                    <!-- Textarea -->
                    <textarea
                      ref="textareaRef"
                      v-model="input"
                      rows="1"
                      placeholder="Ask anything..."
                      class="flex-1 bg-transparent border-0 outline-none text-left text-base sm:text-[17px] text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-500 resize-none py-1.5 leading-relaxed focus:ring-0 max-h-52 overflow-y-auto block self-center"
                      @keydown="onKeydown"
                      @blur="onBlur"
                      @compositionstart="isComposing = true"
                      @compositionend="isComposing = false"
                    />

                    <!-- Right: Cascading Mode Selector -->
                    <CascadingModeSelector :model-value="currentWeightMode" :disabled="isWeightModeSaving || chat.status === 'streaming'" class="shrink-0 self-center" @change="handleUpdateWeightMode" />

                    <!-- Send / Stop Button -->
                    <button
                      type="button"
                      :disabled="!input.trim() && !attachmentIds.length && chat.status !== 'streaming'"
                      :aria-label="chat.status === 'streaming' ? 'Stop response' : 'Send message'"
                      class="rounded-full w-8 h-8 sm:w-8.5 sm:h-8.5 flex items-center justify-center transition-all shrink-0 active:scale-95 self-center"
                      :class="[
                        chat.status === 'streaming' || chat.status === 'submitted'
                          ? 'bg-zinc-800 text-zinc-200 cursor-pointer hover:bg-zinc-700'
                          : (input.trim() || attachmentIds.length)
                            ? 'bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 cursor-pointer hover:opacity-90 shadow-sm'
                            : 'bg-zinc-200/50 dark:bg-zinc-800/50 text-zinc-400 dark:text-zinc-600 cursor-not-allowed'
                      ]"
                      @click="chat.status === 'streaming' ? chat.stop() : handleSubmit($event)"
                    >
                      <UIcon
                        v-if="chat.status === 'streaming' || chat.status === 'submitted'"
                        name="i-lucide-square"
                        class="w-3.5 h-3.5 fill-current"
                      />
                      <UIcon
                        v-else
                        name="i-lucide-arrow-up"
                        class="w-4 h-4"
                      />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Active Chat Messages View -->
          <UContainer v-else class="flex-1 flex flex-col gap-4 sm:gap-6 relative" @mouseup="handleTextSelection">

            <UChatMessages
              should-auto-scroll
              :messages="chat.messages"
              :status="chat.status"
              :spacing-offset="isOwner ? 160 : 0"
              :user="{
                side: 'right',
                variant: 'soft',
                ui: {
                  root: 'justify-end items-end w-full',
                  container: 'justify-end max-w-full',
                  body: 'items-end max-w-full',
                  content: 'w-fit max-w-[85%] sm:max-w-[75%] rounded-3xl px-4 py-2.5 bg-zinc-100 dark:bg-zinc-800/90 text-zinc-900 dark:text-zinc-100 border border-zinc-200/80 dark:border-zinc-700/60 shadow-sm ml-auto text-left leading-relaxed',
                  actions: 'w-full flex items-center justify-end'
                }
              }"
              :assistant="{
                side: 'left',
                variant: 'naked',
                ui: {
                  root: 'justify-start items-start w-full',
                  container: 'w-full max-w-full',
                  body: 'w-full max-w-full',
                  content: 'w-full max-w-full text-zinc-900 dark:text-zinc-100',
                  actions: 'w-full flex items-center justify-between'
                }
              }"
              class="pt-(--ui-header-height) pb-4 sm:pb-6 w-full"
            >
              <template #indicator>
                <ProgressIndicator :status="chat.status" :messages="chat.messages" />
              </template>

              <template #content="{ message }">
                <div
                  :id="`msg-${message.id}`"
                  :data-message-id="message.id"
                  :class="message.role === 'user' ? 'w-fit max-w-full text-left' : 'w-full text-left'"
                >
                  <ChatMessageContent
                    :message="message"
                    :editing="isOwner && editingMessageId === message.id"
                    @save="saveEdit"
                    @cancel-edit="cancelEdit"
                  />
                  <p
                    v-if="message.role === 'assistant' && isMemoryRecallMessage(message.id)"
                    class="mt-2 text-xs text-muted"
                    aria-label="From confirmed session memory"
                  >
                    From confirmed session memory
                  </p>
                </div>
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
                  :memory-enabled="sessionFactsAllowed && sessionFactsAvailable"
                  :memory-busy="sessionFactsLoading || sessionFacts.isPending(message.id)"
                  @edit="startEdit"
                  @regenerate="regenerateMessage"
                  @vote="vote"
                  @favorite="handleFavoriteMessage"
                  @suggest="openSuggestModal"
                  @save-memory="saveMessageAsFact"
                />
              </template>
            </UChatMessages>

            <section
              v-if="sessionFactsAllowed && sessionFactsAvailable && (proposedFacts.length || confirmedFacts.length)"
              class="space-y-3 pb-4"
              aria-label="Session memory"
            >
              <FactProposalCard
                v-for="fact in proposedFacts"
                :key="fact.id"
                :fact="fact"
                :pending="sessionFacts.isPending(fact.id)"
                @confirm="confirmFact"
                @revoke="revokeFact"
              />
              <SessionFactPanel
                :facts="confirmedFacts"
                :is-pending="sessionFacts.isPending"
                @revoke="revokeFact"
              />
            </section>

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
                <span>Copy</span>
              </button>
              <div class="w-px h-3.5 bg-zinc-700/60" />
              <button
                type="button"
                class="rounded-full text-zinc-200 hover:text-white hover:bg-zinc-700/60 cursor-pointer px-2.5 py-1 text-xs font-medium flex items-center gap-1.5 transition-colors"
                @pointerdown.stop="openSelectionDrawer"
              >
                <UIcon name="i-heroicons-sparkles" class="w-3.5 h-3.5 text-amber-400" />
                <span>Ask Selection</span>
              </button>
            </div>

            <div v-if="isOwner && deepResearchMode" class="sticky bottom-20 z-10 w-full max-w-3xl sm:max-w-4xl mx-auto px-4 sm:px-0 mb-2">
              <ResearchModeNotice v-model="selectedResearchDocumentIds" />
              <p v-if="researchLaunchError" role="alert" class="px-3 py-2 text-sm text-error">{{ researchLaunchError }}</p>
            </div>

            <div v-if="isOwner" class="sticky bottom-4 z-10 w-full max-w-3xl sm:max-w-4xl mx-auto px-4 sm:px-0">
              <div
                class="w-full rounded-[28px] sm:rounded-[32px] border border-zinc-200/80 dark:border-zinc-800 bg-white/95 dark:bg-zinc-900/95 backdrop-blur-md shadow-[0_6px_30px_-6px_rgba(0,0,0,0.08)] dark:shadow-[0_6px_30px_-6px_rgba(0,0,0,0.4)] hover:border-zinc-300 dark:hover:border-zinc-700 focus-within:border-zinc-400 dark:focus-within:border-zinc-600 focus-within:shadow-[0_10px_38px_-6px_rgba(0,0,0,0.12)] dark:focus-within:shadow-[0_10px_38px_-6px_rgba(0,0,0,0.5)] transition-all duration-200 px-4 py-2 sm:px-5 sm:py-2.5 flex flex-col gap-2 min-h-[56px] sm:min-h-[60px]"
              >
                <!-- Attachment Tray (if attachments selected) -->
                <AttachmentTray
                  ref="attachmentTray"
                  scope="chat"
                  :chat-id="data?.id"
                  :topic-id="topic?.id"
                  hide-trigger
                  :disabled="chat.status === 'streaming'"
                  @change="(ids, reviewed) => { attachmentIds = ids; acceptedNeedsReviewIds = reviewed }"
                />

                <!-- Input Row: [+]  [Input Area]  [🧠 Mode] [^] -->
                <div class="flex items-center gap-2.5 sm:gap-3 w-full">
                  <!-- Left: + Menu Button (Inline with text) -->
                  <div class="flex items-center shrink-0">
                    <UDropdownMenu
                      :items="plusMenuItems"
                      :content="{ align: 'start', sideOffset: 8 }"
                      :ui="{
                        content: 'min-w-44 p-1.5 rounded-2xl bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl border border-zinc-200/80 dark:border-zinc-800/80 shadow-[0_12px_36px_-6px_rgba(0,0,0,0.12)] dark:shadow-[0_12px_36px_-6px_rgba(0,0,0,0.6)] ring-0',
                        group: 'p-0 flex flex-col gap-1',
                        item: 'rounded-xl px-3 py-2 text-xs sm:text-sm font-medium transition-all duration-150 cursor-pointer text-zinc-700 dark:text-zinc-200 hover:text-zinc-900 dark:hover:text-white hover:bg-zinc-100 dark:hover:bg-zinc-800 active:scale-[0.98] select-none flex items-center gap-2.5 data-highlighted:bg-zinc-100 dark:data-highlighted:bg-zinc-800',
                        itemLeadingIcon: 'w-4 h-4 text-zinc-500 dark:text-zinc-400 group-hover:text-zinc-900 dark:group-hover:text-zinc-100 transition-colors',
                        itemTrailing: 'ml-auto flex items-center',
                        itemTrailingIcon: 'w-4 h-4 text-emerald-500 dark:text-emerald-400'
                      }"
                    >
                      <button
                        type="button"
                        aria-label="Add attachments & options"
                        title="Add attachments & options"
                        class="rounded-xl text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800/80 transition-all cursor-pointer w-9 h-9 sm:w-9.5 sm:h-9.5 flex items-center justify-center p-0 shrink-0 active:scale-95"
                      >
                        <UIcon name="i-lucide-plus" class="w-5 h-5 sm:w-5.5 sm:h-5.5" />
                      </button>
                    </UDropdownMenu>
                  </div>

                  <!-- Deep Research badge (only visible when active) -->
                  <span
                    v-if="deepResearchMode"
                    class="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-500 dark:text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-1 rounded-full whitespace-nowrap select-none shrink-0"
                  >
                    <UIcon name="i-lucide-telescope" class="w-3.5 h-3.5" />
                    <span>Deep Research</span>
                    <button
                      type="button"
                      class="hover:bg-emerald-500/20 rounded-full p-0.5 ml-0.5 cursor-pointer inline-flex items-center transition-colors"
                      title="Disable Deep Research"
                      @click.stop="deepResearchMode = false"
                    >
                      <UIcon name="i-lucide-x" class="w-3 h-3" />
                    </button>
                  </span>

                  <!-- Textarea -->
                  <textarea
                    ref="textareaRef"
                    v-model="input"
                    rows="1"
                    placeholder="Send a message or follow up..."
                    class="flex-1 bg-transparent border-0 outline-none text-left text-base sm:text-[17px] text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-500 resize-none py-1.5 leading-relaxed focus:ring-0 max-h-52 overflow-y-auto block self-center"
                    @keydown="onKeydown"
                    @blur="onBlur"
                    @compositionstart="isComposing = true"
                    @compositionend="isComposing = false"
                  />

                  <!-- Right: Cascading Mode Selector -->
                  <CascadingModeSelector :model-value="currentWeightMode" :disabled="isWeightModeSaving || chat.status === 'streaming'" class="shrink-0 self-center" @change="handleUpdateWeightMode" />

                  <!-- Send / Stop Button -->
                  <button
                    type="button"
                    :disabled="!input.trim() && !attachmentIds.length && chat.status !== 'streaming'"
                    :aria-label="chat.status === 'streaming' ? 'Stop response' : 'Send message'"
                    class="rounded-full w-8 h-8 sm:w-8.5 sm:h-8.5 flex items-center justify-center transition-all shrink-0 active:scale-95 self-center"
                    :class="[
                      chat.status === 'streaming' || chat.status === 'submitted'
                        ? 'bg-zinc-800 text-zinc-200 cursor-pointer hover:bg-zinc-700'
                        : (input.trim() || attachmentIds.length)
                          ? 'bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 cursor-pointer hover:opacity-90 shadow-sm'
                          : 'bg-zinc-200/50 dark:bg-zinc-800/50 text-zinc-400 dark:text-zinc-600 cursor-not-allowed'
                    ]"
                    @click="chat.status === 'streaming' ? chat.stop() : handleSubmit($event)"
                  >
                    <UIcon
                      v-if="chat.status === 'streaming' || chat.status === 'submitted'"
                      name="i-lucide-square"
                      class="w-3.5 h-3.5 fill-current"
                    />
                    <UIcon
                      v-else
                      name="i-lucide-arrow-up"
                      class="w-4 h-4"
                    />
                  </button>
                </div>
              </div>
            </div>

          </UContainer>
        </div>

        <!-- In-Flow Right Side Panel Window for Hit Rate Monitoring (Same plane layout, non-overlay) -->
        <HitRateDrawer
          v-if="showHitRateDrawer"
          :open="showHitRateDrawer"
          :messages="chat.messages"
          @update:open="showHitRateDrawer = $event"
        />

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

        <!-- Right Semi-Circular Quick Navigation Dial Widget (Attached to Dark Gray Chat Panel Edge, hidden when HitRate side drawer is open) -->
        <QuickNavDial v-if="!showHitRateDrawer" :messages="chat.messages" />
      </div>
    </template>
  </UDashboardPanel>

  <UDashboardPanel v-else id="chat-unavailable">
    <template #body>
      <div class="flex flex-col gap-4 p-6">
        <h1 class="text-xl font-semibold">Conversation unavailable</h1>
        <p>Sign in and try again. This conversation may be unavailable or outside your access.</p>
        <ULink to="/">Return to chat</ULink>
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
    @submit="toast.add({ title: 'Feedback submitted and saved to Soul', color: 'success' })"
  />

</template>

<style scoped>
:deep([data-slot="container"]) {
  width: 100% !important;
}

:deep([data-slot="body"]) {
  width: 100% !important;
  max-width: 100% !important;
}

:deep([data-slot="actions"]) {
  width: 100% !important;
  display: flex !important;
  align-items: center !important;
  justify-content: space-between !important;
}
</style>
