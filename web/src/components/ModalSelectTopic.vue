<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
  open: boolean
  chatId?: string
  topics: Array<{
    id: string
    title: string
    mainChatId?: string
  }>
}>()

const emit = defineEmits<{
  (e: 'update:open', val: boolean): void
  (e: 'selectTopic', topicId: string): void
  (e: 'createNewTopic'): void
}>()

const searchQuery = ref('')

const filteredTopics = computed(() => {
  if (!searchQuery.value.trim()) return props.topics
  const q = searchQuery.value.toLowerCase().trim()
  return props.topics.filter(t => (t.title || 'Untitled Topic').toLowerCase().includes(q))
})

function handleSelect(topicId: string) {
  emit('selectTopic', topicId)
  emit('update:open', false)
}
</script>

<template>
  <UModal
    :open="open"
    :ui="{ width: 'sm:max-w-md' }"
    @update:open="emit('update:open', $event)"
  >
    <template #content>
      <div class="p-6 bg-zinc-950 text-zinc-100 rounded-3xl space-y-4 border border-zinc-800 shadow-2xl">
        <!-- Header -->
        <div class="flex items-center justify-between pb-3 border-b border-zinc-800">
          <div class="flex items-center gap-2">
            <UIcon name="i-heroicons-folder-plus" class="w-5 h-5 text-emerald-400" />
            <h3 class="text-base font-bold text-zinc-100">Add to Topic</h3>
          </div>
          <UButton
            color="neutral"
            variant="ghost"
            icon="i-heroicons-x-mark"
            size="xs"
            class="rounded-full text-zinc-400 hover:text-white"
            @click="emit('update:open', false)"
          />
        </div>

        <p class="text-xs text-zinc-400">
          Select a topic space to move this conversation under:
        </p>

        <!-- Search Bar -->
        <div v-if="topics.length > 3">
          <UInput
            v-model="searchQuery"
            icon="i-heroicons-magnifying-glass"
            placeholder="Search topic..."
            size="sm"
            class="w-full bg-zinc-900 border-zinc-800 rounded-xl text-xs"
          />
        </div>

        <!-- Empty Topics State -->
        <div v-if="!topics.length" class="text-center py-8 space-y-3 bg-zinc-900/40 rounded-2xl border border-zinc-800/80">
          <UIcon name="i-heroicons-squares-2x2" class="w-8 h-8 text-zinc-600 mx-auto" />
          <p class="text-xs text-zinc-400">No topics space created yet.</p>
          <UButton
            color="emerald"
            variant="soft"
            size="xs"
            icon="i-heroicons-plus"
            @click="emit('createNewTopic'); emit('update:open', false)"
          >
            Create New Topic
          </UButton>
        </div>

        <!-- Topics List -->
        <div v-else class="space-y-1.5 max-h-64 overflow-y-auto pr-1">
          <div
            v-for="topic in filteredTopics"
            :key="topic.id"
            class="group flex items-center justify-between p-3 bg-zinc-900/80 hover:bg-zinc-900 border border-zinc-800 hover:border-emerald-500/50 rounded-xl cursor-pointer transition-all"
            @click="handleSelect(topic.id)"
          >
            <div class="flex items-center gap-3 min-w-0 flex-1">
              <UIcon name="i-heroicons-squares-2x2" class="w-4 h-4 text-emerald-400 shrink-0" />
              <span class="text-xs font-semibold text-zinc-200 group-hover:text-white truncate">
                {{ topic.title || 'Untitled Topic' }}
              </span>
            </div>
            <UIcon name="i-heroicons-chevron-right" class="w-4 h-4 text-zinc-500 group-hover:text-emerald-400 group-hover:translate-x-0.5 transition-transform" />
          </div>
        </div>
      </div>
    </template>
  </UModal>
</template>
