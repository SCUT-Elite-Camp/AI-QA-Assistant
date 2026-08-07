<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  open: boolean
  topicId: string
  soulContent: string
}>()

const emit = defineEmits<{
  (e: 'update:open', val: boolean): void
  (e: 'saveSoul', newSoul: string): void
}>()

const isEditing = ref(false)
const localSoul = ref(props.soulContent)

watch(() => props.soulContent, (val) => {
  localSoul.value = val
})

function handleSave() {
  emit('saveSoul', localSoul.value)
  isEditing.value = false
}
</script>

<template>
  <UModal :model-value="open" prevent-close :ui="{ width: 'sm:max-w-2xl' }" @update:model-value="emit('update:open', $event)">
    <UCard :ui="{ ring: '', divide: 'divide-y divide-zinc-200 dark:divide-zinc-800' }">
      <template #header>
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2 font-semibold text-zinc-900 dark:text-zinc-100">
            <UIcon name="i-heroicons-cpu-chip" class="w-5 h-5 text-emerald-500" />
            <span>话题记忆 (Soul.md)</span>
          </div>
          <UButton color="gray" variant="ghost" icon="i-heroicons-x-mark" size="xs" @click="emit('update:open', false)" />
        </div>
      </template>

      <div class="py-2 space-y-4">
        <div class="text-xs text-zinc-500 dark:text-zinc-400 bg-zinc-50 dark:bg-zinc-800/60 p-2.5 rounded-lg border border-zinc-200 dark:border-zinc-700/60 flex items-center justify-between">
          <span>Soul 记录了 AI 对本话题的核心实体、场景边界与背景理解，会在请求中约束 Agent 思考。</span>
          <UButton
            v-if="!isEditing"
            color="emerald"
            variant="soft"
            size="2xs"
            icon="i-heroicons-pencil-square"
            @click="isEditing = true"
          >
            编辑修正
          </UButton>
        </div>

        <div v-if="!isEditing" class="p-4 bg-zinc-900 text-zinc-100 rounded-lg font-mono text-xs leading-relaxed whitespace-pre-wrap max-h-[50vh] overflow-y-auto border border-zinc-800">
          {{ localSoul || '暂无 Soul 认知内容' }}
        </div>

        <div v-else class="space-y-3">
          <UTextarea
            v-model="localSoul"
            :rows="12"
            class="font-mono text-xs"
            placeholder="编辑 Soul.md 内容..."
          />
          <div class="flex justify-end gap-2">
            <UButton color="gray" size="xs" @click="isEditing = false">取消</UButton>
            <UButton color="emerald" size="xs" icon="i-heroicons-check" @click="handleSave">保存修正</UButton>
          </div>
        </div>
      </div>
    </UCard>
  </UModal>
</template>
