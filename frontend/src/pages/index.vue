<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { $fetch } from 'ofetch'
import { useToast } from '@nuxt/ui/composables'
import { useChats } from '../composables/useChats'
import { useCsrf } from '../composables/useCsrf'
import { useUserSession } from '../composables/useUserSession'
import Navbar from '../components/Navbar.vue'
import CascadingModeSelector from '../components/chat/CascadingModeSelector.vue'
import AttachmentTray from '../components/chat/AttachmentTray.vue'
import ResearchModeNotice from '../components/research/ResearchModeNotice.vue'
import { useResearchLaunch } from '../composables/useResearchLaunch'

const { fetchChats } = useChats()
const { csrf, headerName } = useCsrf()
const { user, fetchSession } = useUserSession()
const input = ref('')
const textareaRef = ref<HTMLTextAreaElement | null>(null)
void textareaRef
const isComposing = ref(false)
const toast = useToast()
const attachmentIds = ref<string[]>([])
const acceptedNeedsReviewIds = ref<string[]>([])
const attachmentTray = ref<InstanceType<typeof AttachmentTray> | null>(null)
const attachmentCount = ref(0)
const hasAttachments = computed(() => attachmentCount.value > 0 || attachmentIds.value.length > 0)
const useKnowledgeBase = ref(true)
const route = useRoute()
const deepResearchMode = ref(route.query.research === '1')
const selectedResearchDocumentIds = ref<string[]>([])
const { launchResearch, launchingResearch, researchLaunchError } = useResearchLaunch()
watch(() => route.query.research, value => { deepResearchMode.value = value === '1' })
const loading = ref(false)
const router = useRouter()
const submitting = computed(() => loading.value || launchingResearch.value)

function getStoredWeightMode(): 'thinking' | 'auto' | 'fast' {
  if (typeof window !== 'undefined' && window.localStorage) {
    const saved = localStorage.getItem('preferred_weight_mode')
    if (saved === 'fast' || saved === 'auto' || saved === 'thinking') return saved
  }
  return 'thinking'
}

const currentWeightMode = ref<'thinking' | 'auto' | 'fast'>(getStoredWeightMode())

watch(currentWeightMode, (newMode) => {
  if (typeof window !== 'undefined' && window.localStorage && newMode) {
    localStorage.setItem('preferred_weight_mode', newMode)
  }
})

const greeting = computed(() => {
  const hour = new Date().getHours()
  let timeGreeting = 'Good evening'
  if (hour < 12) timeGreeting = 'Good morning'
  else if (hour < 18) timeGreeting = 'Good afternoon'

  const name = user.value?.name?.split(' ')[0] || user.value?.username

  return name ? `${timeGreeting}, ${name}` : timeGreeting
})

async function createChat(prompt: string) {
  if (submitting.value || (!prompt.trim() && !attachmentIds.value.length)) return
  if (deepResearchMode.value) {
    if (attachmentIds.value.length) {
      toast.add({ description: 'Deep Research uses selected knowledge base documents. Remove draft attachments or switch to chat.', color: 'warning' })
      return
    }
    if (await launchResearch(prompt, selectedResearchDocumentIds.value)) input.value = ''
    return
  }
  if (attachmentTray.value?.hasBlockingAttachments()) {
    toast.add({ description: 'Wait for attachment processing and confirm any items that need review.', color: 'warning' })
    return
  }
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
        exploration_mode: 'auto',
      }
    })
    if (chat?.id) {
      input.value = ''
      attachmentTray.value?.resetAfterSend()
      void fetchChats()
      await router.push(`/chat/${chat.id}?mode=${chosenMode}`)
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
  const text = input.value?.trim() || ''
  if (!text && !attachmentIds.value.length) {
    input.value = ''
    return
  }
  void createChat(text)
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

function adjustTextareaHeight() {
  if (textareaRef.value) {
    textareaRef.value.style.height = 'auto'
    textareaRef.value.style.height = `${Math.min(textareaRef.value.scrollHeight, 208)}px`
  }
}

function onBlur() {
  if (!input.value?.trim()) {
    input.value = ''
    if (textareaRef.value) textareaRef.value.style.height = 'auto'
  }
}

const plusMenuItems = computed(() => [
  [
    {
      label: 'Upload attachments / images',
      icon: 'i-lucide-paperclip',
      disabled: deepResearchMode.value || submitting.value,
      onSelect: () => attachmentTray.value?.open()
    },
    {
      label: 'Knowledge base retrieval',
      icon: useKnowledgeBase.value ? 'i-lucide-database-zap' : 'i-lucide-database',
      onSelect: () => { useKnowledgeBase.value = !useKnowledgeBase.value }
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
        <div class="w-full max-w-3xl flex flex-col items-center gap-8 sm:gap-9">
          <!-- Hero Title in Literata -->
          <h1 class="text-3xl sm:text-4xl text-highlighted font-medium font-display tracking-tight select-none text-center">
            {{ greeting }}
          </h1>

          <!-- Deep Research Notice when active -->
          <div v-if="deepResearchMode" class="w-full max-w-2xl">
            <ResearchModeNotice v-model="selectedResearchDocumentIds" />
            <p v-if="researchLaunchError" role="alert" class="px-3 py-2 text-sm text-error">{{ researchLaunchError }}</p>
          </div>

          <!-- Prompt Box (Capsule by default, expands to GPT Card when files are uploaded) -->
          <div class="w-full">
            <div
              class="w-full border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-[0_8px_30px_-6px_rgba(0,0,0,0.08)] dark:shadow-[0_8px_30px_-6px_rgba(0,0,0,0.45)] hover:border-zinc-300 dark:hover:border-zinc-700 focus-within:border-zinc-400 dark:focus-within:border-zinc-600 focus-within:shadow-[0_12px_42px_-6px_rgba(0,0,0,0.12)] dark:focus-within:shadow-[0_12px_42px_-6px_rgba(0,0,0,0.55)] transition-all duration-300"
              :class="[
                hasAttachments
                  ? 'rounded-[26px] px-4.5 pt-3.5 pb-3 sm:px-5 sm:pt-4 sm:pb-3.5 flex flex-col gap-2 min-h-[104px]'
                  : 'rounded-full px-4.5 py-2 sm:px-5 sm:py-2.5 flex items-center gap-3 sm:gap-3.5 min-h-[58px] sm:min-h-[64px]'
              ]"
            >
              <!-- Attachment Tray (always mounted, hidden when no files) -->
              <AttachmentTray
                ref="attachmentTray"
                scope="draft"
                hide-trigger
                :disabled="submitting"
                @change="(ids, reviewed) => { attachmentIds = ids; acceptedNeedsReviewIds = reviewed }"
                @count-change="(count) => attachmentCount = count"
              />

              <!-- Case 1: Uploaded state -> Expanded GPT Card Layout -->
              <template v-if="hasAttachments">
                <!-- Middle: Full-width Textarea -->
                <textarea
                  ref="textareaRef"
                  v-model="input"
                  rows="1"
                  placeholder="Ask anything..."
                  class="w-full bg-transparent border-0 outline-none text-left text-base sm:text-[17px] text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-500 resize-none px-1 py-1 leading-relaxed focus:ring-0 max-h-52 overflow-y-auto block min-h-[36px] sm:min-h-[40px]"
                  @keydown="onKeydown"
                  @blur="onBlur"
                  @input="adjustTextareaHeight"
                  @compositionstart="isComposing = true"
                  @compositionend="isComposing = false"
                />

                <!-- Bottom Toolbar: [+] (Deep Research) ... [Mode] -->
                <div class="flex items-center justify-between w-full pt-1 mt-auto">
                  <!-- Left: Plus Button & Badges -->
                  <div class="flex items-center gap-2 shrink-0">
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
                        class="rounded-full text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800/80 transition-all cursor-pointer w-8.5 h-8.5 sm:w-9 sm:h-9 flex items-center justify-center p-0 shrink-0 active:scale-95"
                      >
                        <UIcon name="i-lucide-plus" class="w-5 h-5 sm:w-5.5 sm:h-5.5" />
                      </button>
                    </UDropdownMenu>

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
                  </div>

                  <!-- Right: Mode Selector -->
                  <CascadingModeSelector
                    v-model="currentWeightMode"
                    expand-on-hover
                    class="shrink-0"
                  />
                </div>
              </template>

              <!-- Case 2: Normal state -> Single-line Elongated Rounded Capsule Bubble -->
              <template v-else>
                <!-- Left: Plus Button -->
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
                      class="rounded-full text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800/80 transition-all cursor-pointer w-8.5 h-8.5 sm:w-9 sm:h-9 flex items-center justify-center p-0 shrink-0 active:scale-95"
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

                <!-- Middle: Textarea (Single-line, flex-1) -->
                <textarea
                  ref="textareaRef"
                  v-model="input"
                  rows="1"
                  placeholder="Ask anything..."
                  class="flex-1 bg-transparent border-0 outline-none text-left text-base sm:text-[18px] text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-500 resize-none py-1 leading-relaxed focus:ring-0 max-h-52 overflow-y-auto block self-center"
                  @keydown="onKeydown"
                  @blur="onBlur"
                  @input="adjustTextareaHeight"
                  @compositionstart="isComposing = true"
                  @compositionend="isComposing = false"
                />

                <!-- Right: Mode Selector -->
                <CascadingModeSelector
                  v-model="currentWeightMode"
                  expand-on-hover
                  class="shrink-0 self-center"
                />
              </template>
            </div>
          </div>
        </div>
      </div>
    </template>
  </UDashboardPanel>
</template>
