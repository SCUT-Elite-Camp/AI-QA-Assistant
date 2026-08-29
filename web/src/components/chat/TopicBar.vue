<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  topic: {
    id: string
    title: string
    weightMode: 'deeper' | 'auto' | 'wider'
    soulContent?: string
  }
}>()

const emit = defineEmits<{
  (e: 'updateMode', mode: 'deeper' | 'auto' | 'wider'): void
  (e: 'openDialogueTree'): void
  (e: 'openDocumentPool'): void
  (e: 'openSoulModal'): void
  (e: 'renameTopic', newTitle: string): void
}>()

const isEditingTitle = ref(false)
const editedTitle = ref(props.topic.title)

function saveTitle() {
  if (editedTitle.value.trim() && editedTitle.value !== props.topic.title) {
    emit('renameTopic', editedTitle.value.trim())
  }
  isEditingTitle.value = false
}
</script>

<template>
  <div class="px-4 py-2 bg-gradient-to-r from-emerald-500/10 via-zinc-100 to-emerald-500/5 dark:from-emerald-950/30 dark:via-zinc-900 dark:to-emerald-950/20 border-b border-emerald-500/20 dark:border-emerald-500/10 flex items-center justify-between gap-3 text-xs">
    <!-- Left: Topic Title & Progressive Indicator -->
    <div class="flex items-center gap-2 overflow-hidden">
      <UBadge color="emerald" variant="subtle" size="xs" class="shrink-0 flex items-center gap-1">
        <UIcon name="i-heroicons-squares-2x2" class="w-3 h-3" />
        <span>话题空间</span>
      </UBadge>

      <div v-if="!isEditingTitle" class="flex items-center gap-1 group font-medium text-zinc-900 dark:text-zinc-100 truncate">
        <span class="truncate" :title="topic.title">{{ topic.title }}</span>
        <UButton
          color="gray"
          variant="ghost"
          icon="i-heroicons-pencil-square"
          size="2xs"
          class="opacity-0 group-hover:opacity-100 transition-opacity"
          @click="isEditingTitle = true"
        />
      </div>

      <div v-else class="flex items-center gap-1">
        <UInput
          v-model="editedTitle"
          size="2xs"
          class="w-36"
          @keyup.enter="saveTitle"
        />
        <UButton color="emerald" size="2xs" icon="i-heroicons-check" @click="saveTitle" />
      </div>
    </div>

    <!-- Middle: Search Weight Mode Selector -->
    <div class="flex items-center gap-1 bg-white dark:bg-zinc-800 p-0.5 rounded-lg border border-zinc-200 dark:border-zinc-700/60 shadow-xs">
      <span class="text-[10px] text-zinc-400 px-1.5 font-mono">检索加权</span>
      <button
        v-for="mode in (['deeper', 'auto', 'wider'] as const)"
        :key="mode"
        class="px-2 py-0.5 rounded text-[11px] font-medium transition-colors"
        :class="topic.weightMode === mode
          ? 'bg-emerald-500 text-white font-semibold shadow-2xs'
          : 'text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200'"
        @click="emit('updateMode', mode)"
      >
        {{ mode === 'deeper' ? 'Deeper 深挖' : mode === 'auto' ? 'Auto 默认' : 'Wider 拓展' }}
      </button>
    </div>

    <!-- Right: Quick Tool Action Icons -->
    <div class="flex items-center gap-1">
      <UTooltip text="Dialogue Tree">
        <UButton
          color="gray"
          variant="ghost"
          icon="i-heroicons-git-branch"
          size="2xs"
          @click="emit('openDialogueTree')"
        >
          Tree
        </UButton>
      </UTooltip>

      <UTooltip text="Document Pool">
        <UButton
          color="gray"
          variant="ghost"
          icon="i-heroicons-folder-open"
          size="2xs"
          @click="emit('openDocumentPool')"
        >
          Docs
        </UButton>
      </UTooltip>

      <UTooltip text="Topic Cognition (Soul.md)">
        <UButton
          color="emerald"
          variant="soft"
          icon="i-heroicons-cpu-chip"
          size="2xs"
          @click="emit('openSoulModal')"
        >
          Soul
        </UButton>
      </UTooltip>
    </div>
  </div>
</template>
