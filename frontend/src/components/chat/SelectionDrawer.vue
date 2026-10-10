<script setup lang="ts">
import { ref, computed, watch, shallowRef } from 'vue'
import { $fetch } from 'ofetch'
import { Chat } from '@ai-sdk/vue'
import { DefaultChatTransport } from 'ai'
import { useRouter } from 'vue-router'
import { useToast } from '@nuxt/ui/composables'
import { useCsrf } from '../../composables/useCsrf'
import { useChats } from '../../composables/useChats'
import ChatMessageContent from './message/MessageContent.vue'
import ChatMessageActions from './message/MessageActions.vue'
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
const temporaryChatId = ref<string>()

function createChat() {
  return new Chat({
    transport: new DefaultChatTransport({
      api: '/api/chats/temp-ask',
      headers: { [headerName]: csrf() },
      prepareSendMessagesRequest: ({ messages }) => ({ body: {
        messages, tempChatId: temporaryChatId.value,
        selectedText: props.selectedText, topicId: props.topicId,
      } }),
    }),
    onData(part) {
      if (part.type === 'data-temp-chat') temporaryChatId.value = String((part.data as { chatId: string }).chatId)
    },
    onError(error) {
      let message = error.message
      if (typeof message === 'string' && message[0] === '{') {
        try { message = JSON.parse(message).message || message } catch { /* keep */ }
      }
      toast.add({ description: message, icon: 'i-lucide-alert-circle', color: 'error' as const, duration: 0 })
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
    temporaryChatId.value = undefined
    chatInstance.value = createChat()
  }
  if (!val) {
    input.value = ''
  }
})

function handleSubmit() {
  const text = input.value.trim()
  if (!text || status.value === 'streaming') return
  chatInstance.value.sendMessage({ text })
  input.value = ''
}

function getFormattedMessages() {
  return messages.value
    .filter(m => m.role === 'user' || m.role === 'assistant')
    .map(m => {
      const text = m.parts?.filter((p: any) => p.type === 'text')?.map((p: any) => p.text)?.join('') || ''
      return { id: m.id, role: m.role, text, parts: JSON.parse(JSON.stringify(m.parts || [])) }
    })
    .filter(m => m.text.trim())
}

// 1. Save as Standalone Independent Chat (not in any topic!)
async function handleSaveStandalone() {
  try {
    const formattedMsgs = getFormattedMessages()
    if (!formattedMsgs.length) {
      toast.add({ title: 'No chat messages to save', color: 'warning' })
      return
    }
    const firstUserMsg = formattedMsgs.find(m => m.role === 'user')
    const initQuery = firstUserMsg?.text || props.selectedText

    const res: any = await $fetch('/api/chats/save-standalone', {
      method: 'POST',
      headers: { [headerName]: csrf() },
      body: {
        initialQuery: initQuery,
        selectedText: props.selectedText,
        contextText: props.contextText,
        sourceChatId: temporaryChatId.value,
        messages: formattedMsgs
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
  }
}
</script>

<template>
  <Transition name="panel">
    <div
      v-if="open"
      class="w-[380px] sm:w-[440px] border-l border-default bg-default flex flex-col shrink-0 h-full relative z-20 shadow-xl overflow-hidden"
    >
      <!-- Header -->
      <div class="px-4 py-3 border-b border-default flex items-center justify-between bg-muted/30">
        <div class="flex items-center gap-2 text-sm font-semibold text-highlighted">
          <UIcon name="i-heroicons-sparkles" class="w-4 h-4 text-neutral-400" />
          <span>Selection Q&A</span>
        </div>
        <div class="flex items-center gap-1.5">
          <!-- Save as Standalone -->
          <UButton
            color="neutral"
            variant="soft"
            icon="i-lucide-bookmark"
            label="Save"
            size="xs"
            class="cursor-pointer font-medium rounded-full"
            @click="handleSaveStandalone"
          />
          <!-- Close -->
          <UButton
            color="neutral"
            variant="ghost"
            icon="i-heroicons-x-mark"
            size="xs"
            class="cursor-pointer ms-1"
            @click="emit('update:open', false)"
          />
        </div>
      </div>

      <!-- Selected text quote card -->
      <div class="px-4 py-3 bg-muted/20 border-b border-default/60 space-y-1.5">
        <div class="text-xs font-medium text-muted flex items-center gap-1">
          <UIcon name="i-heroicons-document-text" class="w-3.5 h-3.5" />
          <span>Selected Quote</span>
        </div>
        <p class="text-xs text-highlighted italic bg-elevated/60 p-2.5 rounded-lg border border-default/60 line-clamp-4 leading-relaxed">
          "{{ selectedText }}"
        </p>
      </div>

      <!-- Chat Messages — Identical format to main chat page -->
      <div class="flex-1 overflow-y-auto min-h-0">
        <!-- Empty state -->
        <div v-if="!visibleMessages.length" class="flex flex-col items-center justify-center h-full gap-3 text-center px-6 py-12">
          <UIcon name="i-heroicons-chat-bubble-left-right" class="w-8 h-8 text-muted/50" />
          <p class="text-xs text-muted">Temporary exploration workspace (isolated from main context)</p>
          <p class="text-[11px] text-muted/60">Click Save at top right to promote to a standalone chat</p>
        </div>

        <!-- Messages — using exact same UChatMessages / ChatMessageContent / ChatMessageActions as main page -->
        <UChatMessages
          v-else
          should-auto-scroll
          :messages="messages"
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
          class="pt-2 pb-4 px-2 w-full"
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
            <ChatMessageActions
              :message="{ ...message, isFavorite: false }"
              :streaming="status === 'streaming' && message.id === messages[messages.length - 1]?.id"
              :editing="false"
              :vote="null"
            />
          </template>
        </UChatMessages>
      </div>

      <!-- Input area -->
      <div class="p-3 border-t border-default bg-default">
        <div class="flex items-center gap-2">
          <UInput
            v-model="input"
            placeholder="Ask a follow-up question..."
            size="sm"
            class="flex-1"
            :disabled="status === 'streaming'"
            @keyup.enter="handleSubmit"
          />
          <UButton
            color="neutral"
            size="sm"
            icon="i-heroicons-paper-airplane"
            :loading="status === 'streaming'"
            :disabled="!input.trim()"
            class="cursor-pointer"
            @click="handleSubmit"
          />
        </div>
      </div>
    </div>
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
