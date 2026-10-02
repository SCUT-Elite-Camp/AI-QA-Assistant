<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { $fetch } from 'ofetch'
import { useToast } from '@nuxt/ui/composables'
import { useChats } from '../composables/useChats'
import { useCsrf } from '../composables/useCsrf'
import { useUserSession } from '../composables/useUserSession'
import Navbar from '../components/Navbar.vue'
import WeightModeSelect from '../components/chat/WeightModeSelect.vue'
import AttachmentTray from '../components/chat/AttachmentTray.vue'

const { fetchChats } = useChats()
const { csrf, headerName } = useCsrf()
const { user, fetchSession } = useUserSession()
const input = ref('')
const toast = useToast()
const attachmentIds = ref<string[]>([])
const acceptedNeedsReviewIds = ref<string[]>([])
const attachmentTray = ref<InstanceType<typeof AttachmentTray> | null>(null)
const useKnowledgeBase = ref(true)
const deepResearchMode = ref(false)
const loading = ref(false)
const router = useRouter()

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
  let timeGreeting = '晚上好'
  if (hour < 6) timeGreeting = '夜深了'
  else if (hour < 12) timeGreeting = '早上好'
  else if (hour < 14) timeGreeting = '中午好'
  else if (hour < 18) timeGreeting = '下午好'

  const name = user.value?.name?.split(' ')[0] || user.value?.username
  return name ? `${timeGreeting}，${name}` : '今天有什么可以帮您？'
})

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
      }
    })
    await fetchChats()
    if (chat?.id) {
      input.value = ''
      attachmentTray.value?.resetAfterSend()
      router.push(`/chat/${chat.id}?mode=${chosenMode}`)
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
      description: '请等待附件解析完成；低置信度附件需要确认后才能发送。',
      icon: 'i-lucide-alert-circle',
      color: 'warning',
    })
    return
  }
  const text = input.value
  createChat(text)
}

const plusMenuItems = computed(() => [[
  {
    label: '上传附件与文档',
    icon: 'i-lucide-paperclip',
    onSelect: () => attachmentTray.value?.open()
  },
  {
    label: deepResearchMode.value ? '关闭深度调研 (Deep Research)' : '开启深度调研 (Deep Research)',
    icon: 'i-lucide-telescope',
    onSelect: () => { deepResearchMode.value = !deepResearchMode.value }
  }
]])
</script>

<template>
  <UDashboardPanel
    id="home"
    class="min-h-0"
    :ui="{ body: 'p-0 sm:p-0' }"
  >
    <template #header>
      <Navbar />
    </template>

    <template #body>
      <div class="flex-1 flex flex-col items-center justify-center px-4 sm:px-6 w-full -mt-12 sm:-mt-16">
        <div class="w-full max-w-2xl sm:max-w-3xl flex flex-col items-center gap-6 sm:gap-8">
          <!-- Hero Title -->
          <div class="text-center space-y-1.5 select-none">
            <h1 class="text-2xl sm:text-3xl font-semibold tracking-tight text-zinc-800 dark:text-zinc-100">
              {{ greeting }}
            </h1>
          </div>

          <!-- Prompt Box Capsule -->
          <div class="w-full">
            <UChatPrompt
              v-model="input"
              :status="loading ? 'streaming' : 'ready'"
              class="[view-transition-name:chat-prompt] w-full rounded-2xl sm:rounded-3xl border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm hover:border-zinc-300 dark:hover:border-zinc-700 focus-within:border-zinc-400 dark:focus-within:border-zinc-600 focus-within:shadow-md transition-all duration-200"
              variant="subtle"
              :ui="{
                base: 'px-2 py-1',
                input: 'text-base placeholder:text-zinc-400 dark:placeholder:text-zinc-500'
              }"
              placeholder="询问企业制度、业务规范或技术方案..."
              @submit="onSubmit"
            >
              <template #header>
                <AttachmentTray
                  ref="attachmentTray"
                  scope="draft"
                  hide-trigger
                  :disabled="loading"
                  @change="(ids, reviewed) => { attachmentIds = ids; acceptedNeedsReviewIds = reviewed }"
                />
              </template>

              <template #footer>
                <!-- Left: Plus Menu for Attachments & Deep Research -->
                <div class="flex items-center gap-2">
                  <UDropdownMenu :items="plusMenuItems" :content="{ align: 'start' }">
                    <UButton
                      color="neutral"
                      variant="ghost"
                      size="sm"
                      icon="i-lucide-plus"
                      aria-label="添加附件与更多功能"
                      title="添加附件与更多功能"
                      class="rounded-full text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors cursor-pointer w-8 h-8 flex items-center justify-center p-0"
                    />
                  </UDropdownMenu>

                  <!-- Deep Research badge (only visible when active) -->
                  <span
                    v-if="deepResearchMode"
                    class="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-500 dark:text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-0.5 rounded-full whitespace-nowrap select-none shrink-0"
                  >
                    <UIcon name="i-lucide-telescope" class="w-3.5 h-3.5" />
                    <span>Deep Research</span>
                    <button
                      type="button"
                      class="hover:bg-emerald-500/20 rounded-full p-0.5 ml-0.5 cursor-pointer inline-flex items-center transition-colors"
                      title="关闭 Deep Research"
                      @click.stop="deepResearchMode = false"
                    >
                      <UIcon name="i-lucide-x" class="w-3 h-3" />
                    </button>
                  </span>
                </div>

                <!-- Right: Model/Weight selector & Submit button -->
                <div class="ms-auto flex items-center gap-1.5">
                  <WeightModeSelect v-model="currentWeightMode" />
                  <UChatPromptSubmit
                    color="neutral"
                    size="sm"
                    class="cursor-pointer rounded-full"
                  />
                </div>
              </template>
            </UChatPrompt>

            <!-- Bottom Disclaimer -->
            <p class="text-center text-xs text-zinc-400 dark:text-zinc-500 mt-3 select-none">
              AI 内容生成自企业知识库与大模型，仅供内部参考，请以原始业务规范为准
            </p>
          </div>
        </div>
      </div>
    </template>
  </UDashboardPanel>
</template>
