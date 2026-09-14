<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { UIMessage } from 'ai'
import { $fetch } from 'ofetch'
import ChatMessageActions from '../chat/message/MessageActions.vue'
import SuggestionModal from '../chat/SuggestionModal.vue'
import { useCsrf } from '../../composables/useCsrf'
import { useFavorites } from '../../composables/useFavorites'

const props = defineProps<{
  chatId: string
  messageId: string
  text: string
  createdAt?: string
}>()
const emit = defineEmits<{ regenerate: [] }>()
const { csrf, headerName } = useCsrf()
const { notifyFavoriteChanged } = useFavorites()
const vote = ref<boolean | null>(null)
const isFavorite = ref(false)
const ready = ref(false)
const suggestionOpen = ref(false)
const message = computed<UIMessage & { createdAt?: string, isFavorite?: boolean }>(() => ({
  id: props.messageId,
  role: 'assistant',
  parts: [{ type: 'text', text: props.text }],
  createdAt: props.createdAt,
  isFavorite: isFavorite.value,
}))

onMounted(async () => {
  try {
    const persisted = await $fetch<{ isFavorite?: boolean }>('/api/research/messages', {
      method: 'POST',
      headers: { [headerName]: csrf() },
      body: { chatId: props.chatId, messageId: props.messageId, text: props.text, createdAt: props.createdAt },
    })
    isFavorite.value = persisted.isFavorite ?? false
    try {
      const votes = await $fetch<Array<{ messageId: string, isUpvoted: boolean }>>(`/api/chats/votes/${props.chatId}`)
      vote.value = votes.find(item => item.messageId === props.messageId)?.isUpvoted ?? null
    } catch { /* Voting can recover on the next interaction without hiding the action bar. */ }
  } catch {
    // The research answer remains readable if optional feedback persistence is unavailable.
  } finally {
    ready.value = true
  }
})

async function handleFavorite(_message: UIMessage, next: boolean) {
  isFavorite.value = next
  await $fetch(`/api/messages/${props.messageId}/feedback`, {
    method: 'POST', headers: { [headerName]: csrf() }, body: { isFavorite: next },
  })
  notifyFavoriteChanged()
}

async function handleVote(_message: UIMessage, next: boolean) {
  const selected = vote.value === next ? undefined : next
  vote.value = selected ?? null
  await $fetch(`/api/chats/votes/${props.chatId}`, {
    method: 'POST', headers: { [headerName]: csrf() }, body: { messageId: props.messageId, isUpvoted: selected },
  })
  if (next === false && selected === false) suggestionOpen.value = true
}
</script>

<template>
  <div v-if="ready" class="mt-1 flex items-center gap-0.5">
    <ChatMessageActions
      :key="`${messageId}:${isFavorite}`"
      :message="message"
      :streaming="false"
      :editing="false"
      :vote="vote"
      @favorite="handleFavorite"
      @vote="handleVote"
      @regenerate="emit('regenerate')"
    />
  </div>
  <SuggestionModal
    v-if="suggestionOpen"
    :open="suggestionOpen"
    :message-id="messageId"
    @update:open="suggestionOpen = $event"
    @submit="useToast().add({ title: '感谢反馈', description: '改进建议已保存。', color: 'success' })"
  />
</template>
