<script setup lang="ts">
import { ref, computed } from 'vue'
import type { UIMessage } from 'ai'
import { isFileUIPart, isReasoningUIPart, isToolUIPart, getToolName } from 'ai'
import { useClipboard } from '@vueuse/core'
import { getTextFromMessage } from '@nuxt/ui/utils/ai'
import type { FactCategory } from '../../../types/memory'

const props = defineProps<{
  message: UIMessage & { createdAt?: string | Date; isFavorite?: boolean }
  streaming: boolean
  editing: boolean
  vote: boolean | null
  memoryEnabled?: boolean
  memoryBusy?: boolean
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
  saveMemory: [message: UIMessage, category: FactCategory]
  viewReasoning: [message: UIMessage]
}>()

const hasFiles = computed(() => props.message.parts.some(isFileUIPart))
const hasReasoningOrSearch = computed(() => {
  return props.message.parts?.some(p => isReasoningUIPart(p) || (isToolUIPart(p) && (getToolName(p) === 'rag_search' || getToolName(p) === 'web_search' || getToolName(p) === 'google_search')))
})

const clipboard = useClipboard()

const copied = ref(false)

function copy() {
  const text = getTextFromMessage(props.message) || (props.message as any).content || ((props.message.parts as any[])?.[0]?.text) || ''
  clipboard.copy(text)

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

const memoryCategoryItems = [
  {
    label: '保存为目标',
    onSelect: () => emit('saveMemory', props.message, 'GOAL')
  },
  {
    label: '保存为偏好',
    onSelect: () => emit('saveMemory', props.message, 'PREFERENCE')
  },
  {
    label: '保存为计划约束',
    onSelect: () => emit('saveMemory', props.message, 'PLAN_CONSTRAINT')
  }
]

function extractDateFromDoc(title?: string, docId?: string, lastUpdated?: string): Date | null {
  if (lastUpdated) {
    const d = new Date(lastUpdated)
    if (!isNaN(d.getTime())) return d
  }

  const str = `${title || ''} ${docId || ''}`

  // 1. Pattern: YYYY-MM-DD or YYYY_MM_DD or YYYY.MM.DD or YYYY-M-D
  const matchYMD = str.match(/(20\d\d)[-_./](\d{1,2})[-_./](\d{1,2})/)
  if (matchYMD) {
    const [_, y, m, d] = matchYMD
    const parsed = new Date(Number(y), Number(m) - 1, Number(d))
    if (!isNaN(parsed.getTime())) return parsed
  }

  // 2. Pattern: timestamp in filename (e.g. 1786438526789)
  const matchTimestamp = str.match(/17\d{11}/)
  if (matchTimestamp) {
    const parsed = new Date(Number(matchTimestamp[0]))
    if (!isNaN(parsed.getTime())) return parsed
  }

  return null
}

const earliestDataDate = computed<string | null>(() => {
  if (!props.message?.parts || !Array.isArray(props.message.parts)) return null

  const dates: Date[] = []

  for (const part of props.message.parts) {
    const raw = (part as any).output ?? (part as any).result ?? (part as any).toolInvocation?.result ?? (part as any).toolInvocation?.output
    const list = Array.isArray(raw) ? raw : (raw?.citations || [])
    if (Array.isArray(list)) {
      for (const item of list) {
        if (!item) continue
        const d = extractDateFromDoc(item.title, item.doc_id, item.last_updated)
        if (d) {
          dates.push(d)
        }
      }
    }
  }

  if (dates.length === 0) return null

  dates.sort((a, b) => a.getTime() - b.getTime())
  const earliest = dates[0]

  const y = earliest.getFullYear()
  const m = String(earliest.getMonth() + 1).padStart(2, '0')
  const d = String(earliest.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
})
</script>

<template>

  <template v-if="message.role === 'assistant' && !streaming">
    <div class="flex items-center justify-between w-full min-w-full">
      <!-- Left Action Buttons -->
      <div class="flex items-center gap-0.5 shrink-0">
        <UTooltip text="Favorite">
          <UButton
            size="sm"
            :color="isFavorite ? 'warning' : 'neutral'"
            variant="ghost"
            :icon="isFavorite ? 'i-heroicons-star-20-solid' : 'i-heroicons-star'"
            aria-label="Favorite response"
            @click="toggleFavorite"
          />
        </UTooltip>

        <UTooltip text="Copy">
          <UButton
            size="sm"
            :color="copied ? 'primary' : 'neutral'"
            variant="ghost"
            :icon="copied ? 'i-lucide-copy-check' : 'i-lucide-copy'"
            aria-label="Copy response"
            @click="copy"
          />
        </UTooltip>

        <UTooltip text="Good response">
          <UButton
            size="sm"
            :color="vote === true ? 'success' : 'neutral'"
            variant="ghost"
            icon="i-lucide-thumbs-up"
            aria-label="Good response"
            @click="emit('vote', message, true)"
          />
        </UTooltip>

        <UTooltip text="Bad response">
          <UButton
            size="sm"
            :color="vote === false ? 'error' : 'neutral'"
            variant="ghost"
            icon="i-lucide-thumbs-down"
            aria-label="Bad response"
            @click="emit('vote', message, false)"
          />
        </UTooltip>

        <UTooltip text="Regenerate">
          <UButton
            size="sm"
            color="neutral"
            variant="ghost"
            icon="i-lucide-rotate-cw"
            aria-label="Regenerate response"
            @click="emit('regenerate', message)"
          />
        </UTooltip>

        <UTooltip v-if="hasReasoningOrSearch" text="查看推理过程">
          <UButton
            size="sm"
            color="neutral"
            variant="ghost"
            icon="i-lucide-brain"
            aria-label="查看推理过程"
            @click="emit('viewReasoning', message)"
          />
        </UTooltip>
      </div>

      <!-- Right Side: Earliest Data Cutoff Date (Far Right, No Icon) -->
      <div
        v-if="earliestDataDate"
        class="text-[11px] font-mono text-zinc-500 select-none text-right shrink-0 pr-1 tracking-tight"
        :title="`Based on knowledge data as of ${earliestDataDate}`"
      >
        Data as of {{ earliestDataDate }}
      </div>
    </div>
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

    <UTooltip text="Copy">
      <UButton
        size="sm"
        :color="copied ? 'primary' : 'neutral'"
        variant="ghost"
        :icon="copied ? 'i-lucide-copy-check' : 'i-lucide-copy'"
        aria-label="Copy prompt"
        @click="copy"
      />
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

    <UDropdownMenu
      v-if="memoryEnabled"
      :items="memoryCategoryItems"
      :content="{ align: 'end' }"
    >
      <UButton
        size="sm"
        color="neutral"
        variant="ghost"
        icon="i-lucide-brain"
        aria-label="Save as session memory"
        :disabled="memoryBusy"
      />
    </UDropdownMenu>
  </template>
</template>
