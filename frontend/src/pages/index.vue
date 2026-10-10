<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { $fetch } from 'ofetch'
import { useToast } from '@nuxt/ui/composables'
import { useChats } from '../composables/useChats'
import { useCsrf } from '../composables/useCsrf'
import { useUserSession } from '../composables/useUserSession'
import Navbar from '../components/Navbar.vue'
import WeightModeSelect from '../components/chat/WeightModeSelect.vue'
import AttachmentTray from '../components/chat/AttachmentTray.vue'
import ResearchModeNotice from '../components/research/ResearchModeNotice.vue'
import { useResearchLaunch } from '../composables/useResearchLaunch'

const { fetchChats } = useChats()
const { csrf, headerName } = useCsrf()
const { user, fetchSession } = useUserSession()
const input = ref('')
const toast = useToast()
const attachmentIds = ref<string[]>([])
const acceptedNeedsReviewIds = ref<string[]>([])
const attachmentTray = ref<InstanceType<typeof AttachmentTray> | null>(null)
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
  void createChat(input.value)
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

const plusMenuItems = computed(() => [[
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
          :status="submitting ? 'streaming' : 'ready'"
          class="[view-transition-name:chat-prompt] rounded-2xl shadow-md"
          variant="subtle"
          :ui="{ base: 'px-1.5' }"
          placeholder="Ask me anything..."
          @submit="onSubmit"
        >
          <template #header>
            <ResearchModeNotice v-if="deepResearchMode" v-model="selectedResearchDocumentIds" />
            <p v-if="deepResearchMode && researchLaunchError" role="alert" class="px-3 py-2 text-sm text-error">{{ researchLaunchError }}</p>
            <AttachmentTray
              ref="attachmentTray"
              scope="draft"
              hide-trigger
              :disabled="submitting"
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
                aria-label="Attachments and more"
                title="Attachments and more"
                :class="['rounded-full cursor-pointer transition-transform', deepResearchMode ? 'text-emerald-400 rotate-45' : 'text-zinc-400 hover:text-zinc-100']"
              />
            </UDropdownMenu>

            <span
              v-if="useKnowledgeBase && !deepResearchMode"
              class="inline-flex items-center gap-1 text-xs font-medium text-primary bg-primary/10 hover:bg-primary/20 transition-colors px-2.5 py-0.5 rounded-full whitespace-nowrap select-none shrink-0"
            >
              <UIcon name="i-lucide-database" class="w-3.5 h-3.5" />
              <span>Knowledge base retrieval</span>
              <button
                type="button"
                class="hover:text-primary-foreground hover:bg-primary/40 rounded-full p-0.5 ml-0.5 cursor-pointer inline-flex items-center"
                title="Disable knowledge base retrieval" aria-label="Disable knowledge base retrieval"
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
                title="Disable Deep Research" aria-label="Disable Deep Research"
                @click.stop="deepResearchMode = false"
              >
                <UIcon name="i-lucide-x" class="w-3 h-3" />
              </button>
            </span>

            <!-- Right: WeightMode + Submit -->
            <div class="ms-auto flex items-center gap-1">
              <WeightModeSelect v-if="!deepResearchMode" v-model="currentWeightMode" />
              <UChatPromptSubmit :disabled="submitting" color="neutral" size="sm" class="cursor-pointer" />
            </div>
          </template>
        </UChatPrompt>

        <div class="flex flex-wrap gap-2">
          <UButton
            v-for="quickChat in quickChats"
            :key="quickChat.label"
            :disabled="submitting"
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
