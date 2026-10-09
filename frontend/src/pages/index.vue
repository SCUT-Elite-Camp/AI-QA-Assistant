<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { $fetch } from 'ofetch'
import { useToast } from '@nuxt/ui/composables'
import { useTextareaAutosize } from '@vueuse/core'
import { useChats } from '../composables/useChats'
import { useCsrf } from '../composables/useCsrf'
import { useUserSession } from '../composables/useUserSession'
import Navbar from '../components/Navbar.vue'
import AttachmentTray from '../components/chat/AttachmentTray.vue'
import CascadingModeSelector from '../components/chat/CascadingModeSelector.vue'

const { fetchChats } = useChats()
const { csrf, headerName } = useCsrf()
const { user, fetchSession } = useUserSession()
const { textarea: textareaRef, input } = useTextareaAutosize({ input: '' })
const isComposing = ref(false)
const toast = useToast()
const attachmentIds = ref<string[]>([])
const acceptedNeedsReviewIds = ref<string[]>([])
const attachmentTray = ref<InstanceType<typeof AttachmentTray> | null>(null)
const useKnowledgeBase = ref(true)
const deepResearchMode = ref(false)
const loading = ref(false)
const router = useRouter()

const currentWeightMode = ref<'thinking' | 'auto' | 'fast'>('fast')

async function createChat(prompt: string) {
  if (loading.value || (!prompt.trim() && !attachmentIds.value.length)) return
  const chosenMode = currentWeightMode.value
  loading.value = true
  try {
    if (!user.value) {
      await fetchSession()
    }
    const chat = await $fetch('/api/chats', {
      method: 'POST',
      headers: { [headerName]: csrf() },
      body: {
        input: prompt,
        attachment_ids: attachmentIds.value,
        accepted_needs_review_ids: acceptedNeedsReviewIds.value,
        knowledge_base_retrieval_enabled: useKnowledgeBase.value,
        exploration_mode: deepResearchMode.value ? 'force' : 'auto',
        weight_mode: chosenMode,
      }
    })
    await fetchChats()
    if (chat?.id) {
      input.value = ''
      attachmentTray.value?.resetAfterSend()
      router.push(`/chat/${chat.id}`)
    }
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : 'Failed to create chat'
    console.error('createChat error:', msg)
    toast.add({ description: msg, icon: 'i-lucide-alert-circle', color: 'error' })
  } finally {
    loading.value = false
  }
}

function onSubmit() {
  if (attachmentTray.value?.hasBlockingAttachments()) {
    toast.add({
      description: 'Please wait for attachments to finish processing; low confidence items require confirmation before sending.',
      icon: 'i-lucide-alert-circle',
      color: 'warning',
    })
    return
  }
  const text = input.value?.trim() || ''
  if (!text && !attachmentIds.value.length) {
    input.value = ''
    return
  }
  createChat(text)
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !isComposing.value) {
    e.preventDefault()
    if (!input.value?.trim() && !attachmentIds.value.length) {
      input.value = ''
      return
    }
    onSubmit()
  }
}

function onBlur() {
  if (!input.value?.trim()) {
    input.value = ''
  }
}

const plusMenuItems = computed(() => [
  [
    {
      label: 'Attach Files',
      icon: 'i-lucide-paperclip',
      onSelect: () => attachmentTray.value?.open()
    },
    {
      label: 'Deep Research',
      icon: 'i-lucide-telescope',
      type: 'checkbox' as const,
      checked: deepResearchMode.value,
      onSelect: () => { deepResearchMode.value = !deepResearchMode.value }
    }
  ]
])

</script>

<template>
  <UDashboardPanel
    id="home"
    class="min-h-0 h-full"
    :ui="{ body: 'p-0 sm:p-0 h-full flex flex-col' }"
  >
    <template #header>
      <Navbar />
    </template>

    <template #body>
      <div class="flex-1 flex flex-col items-center justify-center px-4 sm:px-6 w-full h-full min-h-0">
        <div class="w-full max-w-3xl sm:max-w-4xl flex flex-col items-center gap-8">
          <!-- Hero Title -->
          <h1 class="text-3xl sm:text-4xl font-semibold tracking-tight text-zinc-800 dark:text-zinc-100 select-none">
            What can I help you with today?
          </h1>

          <!-- Prompt Box Capsule (Spacious & Inline) -->
          <div class="w-full">
            <div
              class="w-full rounded-[30px] sm:rounded-[34px] border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-[0_6px_30px_-6px_rgba(0,0,0,0.08)] dark:shadow-[0_6px_30px_-6px_rgba(0,0,0,0.4)] hover:border-zinc-300 dark:hover:border-zinc-700 focus-within:border-zinc-400 dark:focus-within:border-zinc-600 focus-within:shadow-[0_10px_38px_-6px_rgba(0,0,0,0.12)] dark:focus-within:shadow-[0_10px_38px_-6px_rgba(0,0,0,0.5)] transition-all duration-200 px-4 py-2.5 sm:px-5 sm:py-3.5 flex flex-col gap-2.5 min-h-[58px] sm:min-h-[64px]"
            >
              <!-- Attachment Tray (if attachments selected) -->
              <AttachmentTray
                ref="attachmentTray"
                scope="draft"
                hide-trigger
                :disabled="loading"
                @change="(ids, reviewed) => { attachmentIds = ids; acceptedNeedsReviewIds = reviewed }"
              />

              <!-- Input Row: [+]  [Input Area]  [🧠 Mode] [^] -->
              <div class="flex items-center gap-2.5 sm:gap-3 w-full">
                <!-- Left Action: Plus / Attachment Button -->
                <div class="flex items-center shrink-0">
                  <UDropdownMenu
                    :items="plusMenuItems"
                    :content="{ align: 'start', sideOffset: 8 }"
                    :ui="{
                      content: 'min-w-44 p-1.5 rounded-2xl bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl border border-zinc-200/80 dark:border-zinc-800/80 shadow-[0_12px_36px_-6px_rgba(0,0,0,0.12)] dark:shadow-[0_12px_36px_-6px_rgba(0,0,0,0.6)] ring-0',
                      group: 'p-0 flex flex-col gap-1',
                      item: 'rounded-xl px-3 py-2 text-xs sm:text-sm font-medium transition-all duration-150 cursor-pointer text-zinc-700 dark:text-zinc-200 hover:text-zinc-900 dark:hover:text-white hover:bg-zinc-100 dark:hover:bg-zinc-800 active:scale-[0.98] select-none flex items-center gap-2.5 data-highlighted:bg-zinc-100 dark:data-highlighted:bg-zinc-800',
                      itemLeadingIcon: 'w-4 h-4 text-zinc-500 dark:text-zinc-400 group-hover:text-zinc-900 dark:group-hover:text-zinc-100 transition-colors',
                      itemTrailing: 'ml-auto flex items-center',
                      itemTrailingIcon: 'w-4 h-4 text-emerald-500 dark:text-emerald-400'
                    }"
                  >
                    <button
                      type="button"
                      aria-label="Add attachments & options"
                      title="Add attachments & options"
                      class="rounded-xl text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800/80 transition-all cursor-pointer w-9 h-9 sm:w-9.5 sm:h-9.5 flex items-center justify-center p-0 shrink-0 active:scale-95"
                    >
                      <UIcon name="i-lucide-plus" class="w-5 h-5 sm:w-5.5 sm:h-5.5" />
                    </button>
                  </UDropdownMenu>
                </div>

                <!-- Deep Research badge (only visible when active) -->
                <span
                  v-if="deepResearchMode"
                  class="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-500 dark:text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-1 rounded-full whitespace-nowrap select-none shrink-0"
                >
                  <UIcon name="i-lucide-telescope" class="w-3.5 h-3.5" />
                  <span>Deep Research</span>
                  <button
                    type="button"
                    class="hover:bg-emerald-500/20 rounded-full p-0.5 ml-0.5 cursor-pointer inline-flex items-center transition-colors"
                    title="Disable Deep Research"
                    @click.stop="deepResearchMode = false"
                  >
                    <UIcon name="i-lucide-x" class="w-3 h-3" />
                  </button>
                </span>

                <!-- Textarea -->
                <textarea
                  ref="textareaRef"
                  v-model="input"
                  rows="1"
                  placeholder="Ask anything..."
                  class="flex-1 bg-transparent border-0 outline-none text-left text-base sm:text-[17px] text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-500 resize-none py-1.5 leading-relaxed focus:ring-0 max-h-52 overflow-y-auto block self-center"
                  @keydown="onKeydown"
                  @blur="onBlur"
                  @compositionstart="isComposing = true"
                  @compositionend="isComposing = false"
                />

                <!-- Right: Cascading Mode Selector -->
                <CascadingModeSelector v-model="currentWeightMode" class="shrink-0 self-center" />

                <!-- Send Button -->
                <button
                  type="button"
                  :disabled="!input.trim() && !attachmentIds.length || loading"
                  aria-label="Send message"
                  class="rounded-full w-8 h-8 sm:w-8.5 sm:h-8.5 flex items-center justify-center transition-all shrink-0 active:scale-95 self-center"
                  :class="[
                    loading
                      ? 'bg-zinc-800 text-zinc-200 cursor-pointer hover:bg-zinc-700'
                      : (input.trim() || attachmentIds.length)
                        ? 'bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 cursor-pointer hover:opacity-90 shadow-sm'
                        : 'bg-zinc-200/50 dark:bg-zinc-800/50 text-zinc-400 dark:text-zinc-600 cursor-not-allowed'
                  ]"
                  @click="onSubmit"
                >
                  <UIcon
                    v-if="loading"
                    name="i-lucide-loader-2"
                    class="w-4 h-4 animate-spin text-zinc-300"
                  />
                  <UIcon
                    v-else
                    name="i-lucide-arrow-up"
                    class="w-4 h-4"
                  />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>
  </UDashboardPanel>
</template>
