<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  open: boolean
  topicId: string
  currentChatId: string
}>()

const emit = defineEmits<{
  (e: 'update:open', val: boolean): void
  (e: 'selectChat', chatId: string): void
}>()

const loading = ref(false)
const mainChat = ref<any>(null)
const branchChats = ref<any[]>([])

async function fetchDialogues() {
  if (!props.topicId) return
  loading.value = true
  try {
    const res = await fetch(`/api/topics/${props.topicId}/dialogues`)
    if (res.ok) {
      const data = await res.json()
      mainChat.value = data.mainChat
      branchChats.value = data.branchChats || []
    }
  } catch (e) {
    console.error('Failed to fetch dialogues:', e)
  } finally {
    loading.value = false
  }
}

watch(() => props.open, (val) => {
  if (val) fetchDialogues()
})
</script>

<template>
  <UModal :model-value="open" @update:model-value="emit('update:open', $event)">
    <UCard :ui="{ root: 'ring-0 divide-y divide-zinc-200 dark:divide-zinc-800' }">
      <template #header>
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2 font-semibold text-zinc-900 dark:text-zinc-100">
            <UIcon name="i-heroicons-git-branch" class="w-5 h-5 text-emerald-500" />
            <span>话题对话树脉络</span>
          </div>
          <UButton color="neutral" variant="ghost" icon="i-heroicons-x-mark" size="xs" @click="emit('update:open', false)" />
        </div>
      </template>

      <div class="py-2 space-y-4 max-h-[60vh] overflow-y-auto">
        <div v-if="loading" class="text-center py-8 text-zinc-400 text-xs flex items-center justify-center gap-2">
          <UIcon name="i-heroicons-arrow-path" class="w-4 h-4 animate-spin" />
          <span>加载对话脉络...</span>
        </div>

        <div v-else class="space-y-4">
          <!-- Main Chat Card -->
          <div v-if="mainChat" class="space-y-1.5">
            <div class="text-xs font-semibold text-zinc-500 uppercase tracking-wider flex items-center gap-1">
              <UIcon name="i-heroicons-pin" class="w-3.5 h-3.5 text-amber-500" />
              <span>主对话</span>
            </div>
            <div
              class="p-3 rounded-lg border transition-all cursor-pointer flex items-center justify-between gap-3"
              :class="mainChat.id === currentChatId
                ? 'bg-emerald-500/10 border-emerald-500/50 text-emerald-900 dark:text-emerald-200'
                : 'bg-zinc-50 dark:bg-zinc-800/60 border-zinc-200 dark:border-zinc-700/60 hover:border-emerald-500/30'"
              @click="emit('selectChat', mainChat.id)"
            >
              <div class="truncate">
                <div class="font-medium text-sm truncate">{{ mainChat.title || '主对话' }}</div>
                <div class="text-xs text-zinc-400 mt-0.5">{{ mainChat.messages?.length || 0 }} 条消息</div>
              </div>
              <UBadge v-if="mainChat.id === currentChatId" color="success" variant="subtle" size="xs">当前</UBadge>
            </div>
          </div>

          <!-- Branch Chats List -->
          <div class="space-y-1.5">
            <div class="text-xs font-semibold text-zinc-500 uppercase tracking-wider flex items-center gap-1">
              <UIcon name="i-heroicons-git-fork" class="w-3.5 h-3.5 text-emerald-500" />
              <span>正式分支对话 ({{ branchChats.length }})</span>
            </div>

            <div v-if="!branchChats.length" class="text-xs text-zinc-400 italic py-4 text-center border border-dashed rounded-lg">
              暂无分支对话。可以在 AI 回答中划选文本或点击「新建分支」开启分支探讨。
            </div>

            <div v-else class="space-y-2">
              <div
                v-for="branch in branchChats"
                :key="branch.id"
                class="p-3 rounded-lg border transition-all cursor-pointer flex items-center justify-between gap-3"
                :class="branch.id === currentChatId
                  ? 'bg-emerald-500/10 border-emerald-500/50 text-emerald-900 dark:text-emerald-200'
                  : 'bg-zinc-50 dark:bg-zinc-800/60 border-zinc-200 dark:border-zinc-700/60 hover:border-emerald-500/30'"
                @click="emit('selectChat', branch.id)"
              >
                <div class="truncate">
                  <div class="font-medium text-xs truncate flex items-center gap-1.5">
                    <UIcon name="i-heroicons-arrow-turn-down-right" class="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                    <span>{{ branch.title }}</span>
                  </div>
                  <div class="text-[11px] text-zinc-400 mt-1">
                    {{ new Date(branch.createdAt).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }}
                  </div>
                </div>
                <UBadge v-if="branch.id === currentChatId" color="success" variant="subtle" size="xs">当前</UBadge>
              </div>
            </div>
          </div>
        </div>
      </div>
    </UCard>
  </UModal>
</template>
