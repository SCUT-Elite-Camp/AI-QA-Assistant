<script setup lang="ts">
import { useToast } from '@nuxt/ui/composables'
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { $fetch } from 'ofetch'
import { useChats } from '../composables/useChats'
import { useCsrf } from '../composables/useCsrf'
import { useUserSession } from '../composables/useUserSession'
import Navbar from '../components/Navbar.vue'
import WeightModeSelect from '../components/chat/WeightModeSelect.vue'
import AttachmentTray from '../components/chat/AttachmentTray.vue'

const { fetchChats } = useChats()
const { csrf, headerName } = useCsrf()
const { user } = useUserSession()
const input = ref('')

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

const loading = ref(false)
const router = useRouter()
const toast = useToast()
const attachmentIds = ref<string[]>([])
const acceptedNeedsReviewIds = ref<string[]>([])
const attachmentTray = ref<InstanceType<typeof AttachmentTray> | null>(null)
const useKnowledgeBase = ref(true)


const greeting = computed(() => {
  const hour = new Date().getHours()
  let timeGreeting = 'Good evening'
  if (hour < 12) timeGreeting = 'Good morning'
  else if (hour < 18) timeGreeting = 'Good afternoon'

  const name = user.value?.name?.split(' ')[0] || user.value?.username

  return name ? `${timeGreeting}, ${name}` : timeGreeting
})

async function createChat(prompt: string) {
  if (loading.value || (!prompt.trim() && !attachmentIds.value.length)) return
  const chosenMode = currentWeightMode.value
  loading.value = true
  try {
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

const quickChats = [
  { label: 'Introduce yourself', icon: 'i-lucide-bot' },
  { label: "What's the weather today?", icon: 'i-lucide-sun' },
  { label: 'Help me analyze sales data', icon: 'i-lucide-line-chart' },
  { label: 'What is a vector database?', icon: 'i-lucide-database' },
  { label: 'Write a Vue 3 component example', icon: 'i-logos-vue' },
  { label: 'How to optimize RAG retrieval?', icon: 'i-lucide-search' },
  { label: 'Explain the Transformer architecture', icon: 'i-lucide-brain' },
]

const deepResearchMode = ref(false)

const plusMenuItems = computed(() => [[
  {
    label: '上传附件 / 图片',
    icon: 'i-lucide-paperclip',
    onSelect: () => attachmentTray.value?.open()
  },
  {
    label: '企业知识库检索',
    icon: useKnowledgeBase.value ? 'i-lucide-database-zap' : 'i-lucide-database',
    onSelect: () => { useKnowledgeBase.value = !useKnowledgeBase.value }
  },
  {
    label: 'Deep Research',
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
      <UContainer class="flex-1 flex flex-col justify-center gap-4 sm:gap-6 py-8">
        <h1 class="text-3xl sm:text-4xl text-highlighted font-bold">
          {{ greeting }}
        </h1>

        <UChatPrompt
          v-model="input"
          :status="loading ? 'streaming' : 'ready'"
          class="[view-transition-name:chat-prompt] rounded-2xl shadow-md"
          variant="subtle"
          :ui="{ base: 'px-1.5' }"
          placeholder="Ask me anything..."
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
            <!-- Left: + Menu Button (ChatGPT Style) -->
            <UDropdownMenu :items="plusMenuItems" :content="{ align: 'start' }">
              <UButton
                color="neutral"
                variant="ghost"
                size="sm"
                icon="i-lucide-plus"
                aria-label="添加附件与更多功能"
                title="添加附件与更多功能"
                :class="['rounded-full cursor-pointer transition-transform', deepResearchMode ? 'text-emerald-400 rotate-45' : 'text-zinc-400 hover:text-zinc-100']"
              />
            </UDropdownMenu>

            <span
              v-if="useKnowledgeBase"
              class="inline-flex items-center gap-1 text-xs font-medium text-primary bg-primary/10 hover:bg-primary/20 transition-colors px-2.5 py-0.5 rounded-full whitespace-nowrap select-none shrink-0"
            >
              <UIcon name="i-lucide-database" class="w-3.5 h-3.5" />
              <span>企业知识库检索</span>
              <button
                type="button"
                class="hover:text-primary-foreground hover:bg-primary/40 rounded-full p-0.5 ml-0.5 cursor-pointer inline-flex items-center"
                title="关闭企业知识库检索"
                @click.stop="useKnowledgeBase = false"
              >
                <UIcon name="i-lucide-x" class="w-3 h-3" />
              </button>
            </span>

            <span
              v-if="deepResearchMode"
              class="inline-flex items-center gap-1 text-xs font-medium text-emerald-400 bg-emerald-400/10 hover:bg-emerald-400/20 transition-colors px-2.5 py-0.5 rounded-full whitespace-nowrap select-none shrink-0"
            >
              <UIcon name="i-lucide-telescope" class="w-3.5 h-3.5" />
              <span>Deep Research</span>
              <button
                type="button"
                class="hover:bg-emerald-400/40 rounded-full p-0.5 ml-0.5 cursor-pointer inline-flex items-center"
                title="关闭 Deep Research"
                @click.stop="deepResearchMode = false"
              >
                <UIcon name="i-lucide-x" class="w-3 h-3" />
              </button>
            </span>

            <!-- Right: WeightMode + Submit -->
            <div class="ms-auto flex items-center gap-1">
              <WeightModeSelect v-model="currentWeightMode" />
              <UChatPromptSubmit color="neutral" size="sm" class="cursor-pointer" />
            </div>
          </template>
        </UChatPrompt>

        <div class="flex flex-wrap gap-2">
          <UButton
            v-for="quickChat in quickChats"
            :key="quickChat.label"
            :icon="quickChat.icon"
            :label="quickChat.label"
            size="sm"
            color="neutral"
            variant="outline"
            class="rounded-full"
            @click="createChat(quickChat.label)"
          />
        </div>
      </UContainer>
    </template>
  </UDashboardPanel>
</template>
