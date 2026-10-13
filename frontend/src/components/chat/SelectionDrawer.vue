<script setup lang="ts">
import { ref, computed, watch, shallowRef, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { $fetch } from 'ofetch'
import { Chat } from '@ai-sdk/vue'
import { DefaultChatTransport, type UIMessage } from 'ai'
import { useClipboard } from '@vueuse/core'
import { getTextFromMessage } from '@nuxt/ui/utils/ai'
import { useRouter } from 'vue-router'
import { useToast } from '@nuxt/ui/composables'
import { useCsrf } from '../../composables/useCsrf'
import { useChats } from '../../composables/useChats'
import ChatMessageContent from './message/MessageContent.vue'
import ChatIndicator from './Indicator.vue'

const props = defineProps<{
  open: boolean
  selectedText: string
  contextText?: string
  chatId: string
  topicId?: string
}>()

const emit = defineEmits<{
  (e: 'update:open', val: boolean): void
}>()

const router = useRouter()
const toast = useToast()
const { csrf, headerName } = useCsrf()
const { fetchChats } = useChats()

const input = ref('')
const inputRef = ref<HTMLTextAreaElement>()
const quoteExpanded = ref(false)
const tempChatId = ref<string>()
const savedMessageIds = ref<string[]>([])
const saving = ref(false)
const copiedMessageId = ref<string>()
const { copy, copied } = useClipboard()
const busy = computed(() => status.value === 'streaming' || status.value === 'submitted')
const canSave = computed(() => !!tempChatId.value && savedMessageIds.value.length > 1 && !busy.value)

function createChat() {
  return new Chat({
    transport: new DefaultChatTransport({
      api: '/api/chats/temp-ask',
      headers: { [headerName]: csrf() },
      body: () => ({
        selectedText: props.selectedText,
        contextText: props.contextText,
        topicId: props.topicId,
        tempChatId: tempChatId.value
      })
    }),
    onData(part) {
      if (part.type === 'data-temp-chat') {
        const data = part.data as { chatId?: string; messageIds?: string[] }
        if (data.chatId) tempChatId.value = data.chatId
        if (data.messageIds) savedMessageIds.value = [...new Set([...savedMessageIds.value, ...data.messageIds])]
      }
    },
    onError(error) {
      let message = error.message
      if (typeof message === 'string' && message[0] === '{') {
        try { message = JSON.parse(message).message || message } catch { /* keep */ }
      }
      const description = /^(agent_unavailable|unverified_answer|persistent_memory_disabled)$/.test(message)
        ? 'Please try again. The selection conversation could not be completed.' : message
      toast.add({ title: 'Could not answer', description, icon: 'i-lucide-alert-circle', color: 'error' })
    }
  })
}

const chatInstance = shallowRef(createChat())

const messages = computed(() => chatInstance.value.messages || [])
const status = computed(() => chatInstance.value.status)
const visibleMessages = computed(() =>
  messages.value.filter(m => m.role === 'user' || m.role === 'assistant')
)

// Recreate chat instance when drawer opens (reset + refresh context)
watch(() => props.open, (val) => {
  if (val) {
    tempChatId.value = undefined
    savedMessageIds.value = []
    quoteExpanded.value = false
    chatInstance.value = createChat()
    nextTick(() => inputRef.value?.focus())
  }
  if (!val) {
    chatInstance.value.stop()
    input.value = ''
  }
})

function handleSubmit() {
  const text = input.value.trim()
  if (!text || busy.value) return
  chatInstance.value.sendMessage({ text })
  input.value = ''
}

function onInputKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    handleSubmit()
  }
}

async function copyMessage(message: UIMessage) {
  await copy(getTextFromMessage(message))
  copiedMessageId.value = message.id
}

onMounted(() => inputRef.value?.focus())
onBeforeUnmount(() => chatInstance.value.stop())

async function handleSaveStandalone() {
  if (!canSave.value || saving.value) return
  saving.value = true
  try {
    const res: any = await $fetch('/api/chats/save-standalone', {
      method: 'POST',
      headers: { [headerName]: csrf() },
      body: {
        sourceChatId: tempChatId.value,
        messages: savedMessageIds.value.map(id => ({ id }))
      }
    })

    if (res?.chat?.id) {
      toast.add({ title: 'Saved as standalone chat', color: 'success' })
      emit('update:open', false)
      await fetchChats()
      router.push(`/chat/${res.chat.id}`)
    }
  } catch (err: any) {
    toast.add({ title: 'Failed to save chat', description: err.message, color: 'error' })
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <Transition name="panel">
    <aside
      v-if="open"
      aria-label="Selection Q&A"
      class="absolute inset-0 md:relative md:inset-auto w-full md:w-[380px] xl:w-[420px] border-l border-default bg-default flex flex-col shrink-0 h-full min-h-0 z-20 overflow-hidden"
    >
      <!-- Header -->
      <div class="px-5 py-4 shrink-0 flex items-center justify-between gap-2">
        <div class="flex items-center gap-2 text-sm font-semibold text-highlighted">
          <UIcon name="i-lucide-message-square-text" class="size-4 text-muted" />
          <span>Selection Q&A</span>
        </div>
        <div class="flex items-center gap-1.5">
          <!-- Save as Standalone -->
          <UButton
            color="neutral"
            variant="ghost"
            icon="i-lucide-bookmark"
            label="Save"
            size="xs"
            class="cursor-pointer rounded-lg"
            title="Save as a separate chat"
            :disabled="!canSave"
            :loading="saving"
            @click="handleSaveStandalone"
          />
          <!-- Close -->
          <UButton
            color="neutral"
            variant="ghost"
            icon="i-lucide-x"
            aria-label="Close selection Q&A"
            size="xs"
            class="cursor-pointer ms-1"
            @click="emit('update:open', false)"
          />
        </div>
      </div>

      <!-- Selected text quote card -->
      <div class="mx-5 mb-3 shrink-0 rounded-xl bg-muted/50 px-3.5 py-3">
        <div class="flex items-start gap-2.5">
          <UIcon name="i-lucide-quote" class="size-4 shrink-0 text-muted mt-0.5" />
          <p class="min-w-0 flex-1 text-sm text-toned leading-relaxed whitespace-pre-wrap" :class="quoteExpanded ? 'max-h-40 overflow-y-auto' : 'line-clamp-2'">{{ selectedText }}</p>
          <button v-if="selectedText.length > 100 || selectedText.includes('\n')" type="button" :aria-expanded="quoteExpanded" :aria-label="quoteExpanded ? 'Collapse selected text' : 'Expand selected text'" class="shrink-0 text-muted hover:text-highlighted cursor-pointer rounded focus-visible:outline-2" @click="quoteExpanded = !quoteExpanded">
            <UIcon :name="quoteExpanded ? 'i-lucide-chevron-up' : 'i-lucide-chevron-down'" class="size-4" />
          </button>
        </div>
      </div>

      <!-- Chat Messages — Identical format to main chat page -->
      <div class="selection-messages flex-1 overflow-y-auto min-h-0 border-t border-default/60">
        <!-- Empty state -->
        <div v-if="!visibleMessages.length" class="flex flex-col items-center justify-center h-full gap-3 text-center px-6 py-8">
          <div class="rounded-2xl bg-muted/50 p-3 text-muted"><UIcon name="i-lucide-message-square-text" class="size-6 block" /></div>
          <p class="text-sm text-muted">What would you like to know?</p>
        </div>

        <!-- Messages — using exact same UChatMessages / ChatMessageContent / ChatMessageActions as main page -->
        <UChatMessages
          v-else
          should-auto-scroll
          :messages="visibleMessages"
          :status="status"
          :spacing-offset="0"
          :user="{
            side: 'right',
            variant: 'soft',
            ui: {
              root: 'justify-end items-end w-full',
              container: 'justify-end max-w-full',
              body: 'items-end max-w-full',
              content: 'w-fit max-w-[88%] rounded-2xl px-3.5 py-2 bg-zinc-100 dark:bg-zinc-800/90 text-zinc-900 dark:text-zinc-100 border border-zinc-200/80 dark:border-zinc-700/60 shadow-sm ml-auto text-left leading-relaxed text-sm',
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
              content: 'w-full max-w-full text-zinc-900 dark:text-zinc-100 text-sm',
              actions: 'w-full flex items-center justify-between'
            }
          }"
          class="pt-4 pb-4 px-4 w-full"
        >
          <template #indicator>
            <div class="flex items-center gap-1.5">
              <ChatIndicator />
              <UChatShimmer text="Thinking..." class="text-sm" />
            </div>
          </template>

          <template #content="{ message }">
            <div :class="message.role === 'user' ? 'w-fit max-w-full text-left' : 'w-full text-left'">
              <ChatMessageContent
                :message="message"
                :editing="false"
              />
            </div>
          </template>

          <template #actions="{ message }">
            <UButton
              v-if="!busy"
              color="neutral"
              variant="ghost"
              size="xs"
              :icon="copied && copiedMessageId === message.id ? 'i-lucide-copy-check' : 'i-lucide-copy'"
              aria-label="Copy selection message"
              title="Copy message"
              class="cursor-pointer rounded-lg text-muted"
              @click="copyMessage(message)"
            />
          </template>
        </UChatMessages>
      </div>

      <!-- Input area -->
      <form class="shrink-0 p-4 pt-3 bg-default" @submit.prevent="handleSubmit">
        <div class="rounded-2xl border border-zinc-200 dark:border-zinc-700/70 bg-zinc-50 dark:bg-zinc-900 shadow-sm focus-within:border-zinc-400 dark:focus-within:border-zinc-500 transition-colors p-3">
          <textarea
            ref="inputRef"
            v-model="input"
            aria-label="Ask about the selection"
            placeholder="Ask about this selection…"
            rows="3"
            class="block w-full min-h-20 max-h-48 resize-y bg-transparent outline-none border-0 text-sm leading-relaxed text-highlighted placeholder:text-muted focus:ring-0"
            @keydown="onInputKeydown"
          />
          <div class="flex items-center justify-between gap-2 pt-2">
            <span class="text-[11px] text-muted">Shift + Enter for a new line</span>
            <button
              :type="busy ? 'button' : 'submit'"
              :aria-label="busy ? 'Stop selection response' : 'Send selection question'"
              :disabled="!busy && !input.trim()"
              class="size-8 rounded-full flex items-center justify-center bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 hover:opacity-80 disabled:opacity-25 disabled:cursor-not-allowed cursor-pointer transition-opacity focus-visible:outline-2 focus-visible:outline-offset-2"
              @click="busy && chatInstance.stop()"
            >
              <UIcon :name="busy ? 'i-lucide-square' : 'i-lucide-arrow-up'" class="size-4" />
            </button>
          </div>
        </div>
      </form>
    </aside>
  </Transition>
</template>

<style scoped>
.panel-enter-active,
.panel-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}
.panel-enter-from,
.panel-leave-to {
  opacity: 0;
  transform: translateX(100%);
}

.selection-messages :deep([data-slot="container"]) {
  width: 100% !important;
}

.selection-messages :deep([data-slot="body"]) {
  width: 100% !important;
  max-width: 100% !important;
}

.selection-messages :deep([data-slot="actions"]) {
  width: 100% !important;
  display: flex !important;
  align-items: center !important;
  justify-content: space-between !important;
}
</style>
