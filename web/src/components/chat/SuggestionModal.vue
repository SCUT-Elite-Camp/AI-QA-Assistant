<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  open: boolean
  messageId: string
}>()

const emit = defineEmits<{
  (e: 'update:open', val: boolean): void
  (e: 'submit', suggestion: string): void
}>()

const suggestion = ref('')
const loading = ref(false)

async function handleSubmit() {
  if (!suggestion.value.trim()) return
  loading.value = true
  try {
    const res = await fetch(`/api/messages/${props.messageId}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ suggestionText: suggestion.value })
    })
    if (res.ok) {
      emit('submit', suggestion.value)
      suggestion.value = ''
      emit('update:open', false)
    }
  } catch (e) {
    console.error('Failed to submit suggestion:', e)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="opacity-0 scale-95"
      enter-to-class="opacity-100 scale-100"
      leave-active-class="transition duration-150 ease-in"
      leave-from-class="opacity-100 scale-100"
      leave-to-class="opacity-0 scale-95"
    >
      <div
        v-if="open"
        class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs"
        @click.self="emit('update:open', false)"
      >
        <div class="w-full max-w-md bg-zinc-900/95 border border-zinc-800 rounded-2xl p-5 shadow-2xl space-y-4">
          <!-- Header -->
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2 font-medium text-zinc-100 text-sm">
              <div class="w-7 h-7 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400">
                <UIcon name="i-heroicons-light-bulb" class="w-4 h-4" />
              </div>
              <span>提出改进建议</span>
            </div>
            <UButton
              color="neutral"
              variant="ghost"
              icon="i-heroicons-x-mark"
              size="xs"
              class="rounded-full text-zinc-400 hover:text-zinc-200"
              @click="emit('update:open', false)"
            />
          </div>

          <!-- Description -->
          <p class="text-xs text-zinc-400 leading-relaxed">
            您的改进建议会与问答对一同沉淀入话题空间的 Soul 认知库中，用以优化后续的精准生成。
          </p>

          <!-- Input Textarea -->
          <textarea
            v-model="suggestion"
            rows="3"
            placeholder="请说明回答不够准确的地方或具体的补充要求..."
            class="w-full px-3.5 py-2.5 text-xs bg-zinc-950/80 border border-zinc-800 rounded-xl text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-amber-500/50 focus:ring-1 focus:ring-amber-500/50 resize-none transition-all"
          />

          <!-- Footer Action Buttons -->
          <div class="flex items-center justify-end gap-2 pt-1">
            <button
              type="button"
              class="px-3.5 py-1.5 text-xs text-zinc-400 hover:text-zinc-200 rounded-xl hover:bg-zinc-800/50 transition-colors"
              @click="emit('update:open', false)"
            >
              取消
            </button>
            <button
              type="button"
              :disabled="!suggestion.trim() || loading"
              class="px-4 py-1.5 text-xs font-medium bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/30 rounded-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5"
              @click="handleSubmit"
            >
              <UIcon v-if="loading" name="i-heroicons-arrow-path" class="w-3.5 h-3.5 animate-spin" />
              <span>提交建议</span>
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

