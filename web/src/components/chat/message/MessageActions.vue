<script setup lang="ts">
import { ref, computed } from 'vue'
import type { UIMessage } from 'ai'
import { isFileUIPart } from 'ai'
import { useClipboard } from '@vueuse/core'
import { getTextFromMessage } from '@nuxt/ui/utils/ai'

const props = defineProps<{
  message: UIMessage & { createdAt?: string | Date; isFavorite?: boolean }
  streaming: boolean
  editing: boolean
  vote: boolean | null
}>()

const formattedDate = computed(() => {
  if (!props.message.createdAt) return null

  const date = new Date(props.message.createdAt)

  return {
    time: date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' }),
    full: date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }),
    iso: date.toISOString()
  }
})

// Initialize from message prop so state survives page refresh
const isFavorite = ref(props.message.isFavorite ?? false)

const emit = defineEmits<{
  edit: [message: UIMessage]
  regenerate: [message: UIMessage]
  vote: [message: UIMessage, isUpvoted: boolean]
  favorite: [message: UIMessage, isFav: boolean]
}>()

const hasFiles = computed(() => props.message.parts.some(isFileUIPart))

const clipboard = useClipboard()

const copied = ref(false)

function copy() {
  clipboard.copy(getTextFromMessage(props.message))

  copied.value = true

  setTimeout(() => {
    copied.value = false
  }, 2000)
}

function toggleFavorite() {
  isFavorite.value = !isFavorite.value
  // Pass the NEW state so the parent can send correct value to API
  emit('favorite', props.message, isFavorite.value)
}
</script>

<template>

  <template v-if="message.role === 'assistant' && !streaming">
    <UTooltip text="收藏此解答">
      <UButton
        size="sm"
        :color="isFavorite ? 'warning' : 'neutral'"
        variant="ghost"
        :icon="isFavorite ? 'i-heroicons-star-20-solid' : 'i-heroicons-star'"
        aria-label="Favorite response"
        @click="toggleFavorite"
      />
    </UTooltip>

    <UTooltip text="复制回答">
      <UButton
        size="sm"
        :color="copied ? 'primary' : 'neutral'"
        variant="ghost"
        :icon="copied ? 'i-lucide-copy-check' : 'i-lucide-copy'"
        aria-label="Copy response"
        @click="copy"
      />
    </UTooltip>

    <UTooltip text="赞">
      <UButton
        size="sm"
        :color="vote === true ? 'success' : 'neutral'"
        variant="ghost"
        icon="i-lucide-thumbs-up"
        aria-label="Good response"
        @click="emit('vote', message, true)"
      />
    </UTooltip>

    <UTooltip text="踩 (提供改进建议)">
      <UButton
        size="sm"
        :color="vote === false ? 'error' : 'neutral'"
        variant="ghost"
        icon="i-lucide-thumbs-down"
        aria-label="Bad response"
        @click="emit('vote', message, false)"
      />
    </UTooltip>

    <UTooltip text="重新生成">
      <UButton
        size="sm"
        color="neutral"
        variant="ghost"
        icon="i-lucide-rotate-cw"
        aria-label="Regenerate response"
        @click="emit('regenerate', message)"
      />
    </UTooltip>
  </template>

  <template v-if="message.role === 'user' && !streaming && !editing">
    <UTooltip
      v-if="formattedDate"
      :text="formattedDate.full"
    >
      <time
        :datetime="formattedDate.iso"
        class="text-xs text-muted mr-1.5"
      >
        {{ formattedDate.time }}
      </time>
    </UTooltip>

    <UTooltip
      v-if="!hasFiles"
      text="Edit message"
    >
      <UButton
        size="sm"
        color="neutral"
        variant="ghost"
        icon="i-lucide-pencil"
        aria-label="Edit message"
        @click="emit('edit', message)"
      />
    </UTooltip>
  </template>
</template>
