<script setup lang="ts">
import { useToast } from '@nuxt/ui/composables'
import { ref, computed } from 'vue'
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
const currentWeightMode = ref<'deeper' | 'auto' | 'wider'>('auto')
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
      }
    })
    await fetchChats()
    if (chat?.id) {
      input.value = ''
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
    label: '上传图片或文件',
    icon: 'i-lucide-paperclip',
    onSelect: () => attachmentTray.value?.open()
  },
  {
    label: '企业知识库检索',
    icon: useKnowledgeBase.value ? 'i-lucide-database-zap' : 'i-lucide-database',
    onSelect: () => { useKnowledgeBase.value = !useKnowledgeBase.value }
  },
  {
    label: deepResearchMode.value ? 'Deep Research: ON' : 'Deep Research',
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
          <template #footer>
            <AttachmentTray
              ref="attachmentTray"
              scope="draft"
              :disabled="loading"
              @change="(ids, reviewed) => { attachmentIds = ids; acceptedNeedsReviewIds = reviewed }"
            />
            <!-- + Menu: Attachments / Knowledge Base / Deep Research -->
            <UDropdownMenu :items="plusMenuItems" :content="{ align: 'start' }">
              <UButton
                color="neutral"
                variant="ghost"
                size="sm"
                icon="i-lucide-plus"
                aria-label="打开更多功能"
                :class="['rounded-full cursor-pointer transition-transform', deepResearchMode ? 'text-emerald-400 rotate-45' : 'text-zinc-400 hover:text-zinc-100']"
              />
            </UDropdownMenu>

            <span
              v-if="useKnowledgeBase"
              class="text-xs font-semibold text-primary bg-primary/10 px-2 py-0.5 rounded-full"
            >企业知识库检索</span>

            <span v-if="deepResearchMode" class="text-xs font-semibold text-emerald-400 bg-emerald-400/10 px-2 py-0.5 rounded-full">Deep Research</span>

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
