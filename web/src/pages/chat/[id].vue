<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { $fetch } from 'ofetch'
import type { UIMessage } from 'ai'
import { useModels } from '../../composables/useModels'
import { useChats } from '../../composables/useChats'
import { useCsrf } from '../../composables/useCsrf'
import { useMockChat } from '../../composables/useMockChat'
import { useBffChat } from '../../composables/useBffChat'
import { useRoute } from 'vue-router'
import ChatMessageContent from '../../components/chat/message/MessageContent.vue'
import ChatMessageActions from '../../components/chat/message/MessageActions.vue'
import ChatVisibility from '../../components/chat/ChatVisibility.vue'
import ChatTitle from '../../components/chat/ChatTitle.vue'
import ChatIndicator from '../../components/chat/Indicator.vue'
import Navbar from '../../components/Navbar.vue'
import type { Vote } from '../../../server/utils/drizzle'

const route = useRoute<'/chat/[id]'>()
const toast = useToast()
const { model } = useModels()
const { chats } = useChats()
const { csrf, headerName } = useCsrf()

// Mock/Real switch
const isMock = import.meta.env.VITE_USE_MOCK !== 'false'
const initialPrompt = typeof route.query.prompt === 'string' ? route.query.prompt : ''

const data = isMock
  ? await $fetch(`/api/chats/${route.params.id}`).catch((e) => {
      console.error('[chat/[id]] fetch failed:', e)
      return null
    })
  : {
      id: String(route.params.id || 'local-session-001'),
      isOwner: true,
      visibility: 'private' as const,
      title: 'BFF Mock Chat',
      messages: [] as UIMessage[],
    }

const isOwner = computed(() => data?.isOwner ?? false)
const visibility = ref<'public' | 'private'>(data?.visibility ?? 'private')
const title = ref<string | null>(data?.title ?? null)

watch(() => chats.value.find(c => c.id === data?.id)?.label, (label) => {
  if (label && label !== 'Untitled') {
    title.value = label
  }
})

const votes = ref<Vote[]>([])
if (isMock && isOwner.value) {
  $fetch(`/api/chats/votes/${route.params.id}`).then((v) => {
    votes.value = v
  }).catch(() => {})
}

const input = ref('')

const chat = isMock
  ? useMockChat({ id: data?.id, messages: data?.messages ?? [], isOwner: isOwner.value })
  : useBffChat({ id: data?.id, messages: data?.messages ?? [] })

function handleSubmit(e: Event) {
  e.preventDefault()
  if (input.value.trim()) {
    chat.sendMessage({ text: input.value })
    input.value = ''
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
  if (isMock) {
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
  }

  editingMessageId.value = null
  chat.sendMessage({ text, messageId: message.id })
}

async function regenerateMessage(message: UIMessage) {
  if (isMock) {
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
  }

  chat.regenerate({ messageId: message.id })
}

function getVote(messageId: string) {
  const vote = votes.value.find(v => v.messageId === messageId)
  if (!vote) return null
  return !!vote.isUpvoted
}

async function vote(message: UIMessage, isUpvoted: boolean) {
  if (!isMock) return

  const snapshot = votes.value.map(v => ({ ...v }))
  const toggling = getVote(message.id) === isUpvoted
  const next = toggling ? null : isUpvoted

  votes.value = next === null
    ? votes.value.filter(v => v.messageId !== message.id)
    : [
        ...votes.value.filter(v => v.messageId !== message.id),
        { chatId: data!.id, messageId: message.id, isUpvoted: next },
      ]

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

// On mount, if chat has only 1 message (unanswered user message), trigger response generation
onMounted(() => {
  if (!isMock && initialPrompt.trim() && chat.messages.length === 0) {
    chat.sendMessage({ text: initialPrompt })
    return
  }

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
  >
    <template #header>
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
    </template>

    <template #body>
      <UContainer class="flex-1 flex flex-col gap-4 sm:gap-6">
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
              <UChatShimmer
                text="Thinking..."
                class="text-sm"
              />
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
              :message="message"
              :streaming="chat.status === 'streaming' && message.id === chat.messages[chat.messages.length - 1]?.id"
              :editing="editingMessageId === message.id"
              :vote="getVote(message.id)"
              @edit="startEdit"
              @regenerate="regenerateMessage"
              @vote="vote"
            />
          </template>
        </UChatMessages>

        <UChatPrompt
          v-if="isOwner"
          v-model="input"
          :error="chat.error"
          variant="subtle"
          class="sticky bottom-0 [view-transition-name:chat-prompt] rounded-b-none z-10"
          :ui="{ base: 'px-1.5' }"
          @submit="handleSubmit"
        >
          <template #footer>
            <ModelSelect v-model="model" />
            <UChatPromptSubmit
              :status="chat.status"
              color="neutral"
              size="sm"
              @stop="chat.stop()"
              @reload="chat.regenerate()"
            />
          </template>
        </UChatPrompt>
      </UContainer>
    </template>
  </UDashboardPanel>

  <UContainer
    v-else
    class="flex-1 flex flex-col gap-4 sm:gap-6"
  >
    <UError
      :error="{ statusMessage: 'Chat not found', statusCode: 404 }"
      class="min-h-full"
    >
      <template #links>
        <UButton
          to="/"
          size="lg"
          label="Go back to home"
        />
      </template>
    </UError>
  </UContainer>
</template>
