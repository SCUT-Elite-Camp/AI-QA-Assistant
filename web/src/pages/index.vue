<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { $fetch } from 'ofetch'
import { useChats } from '../composables/useChats'
import { useCsrf } from '../composables/useCsrf'
import { useUserSession } from '../composables/useUserSession'
import Navbar from '../components/Navbar.vue'
import WeightModeSelect from '../components/chat/WeightModeSelect.vue'
import ResearchModeNotice from '../components/research/ResearchModeNotice.vue'
import { useResearchLaunch } from '../composables/useResearchLaunch'

const { fetchChats } = useChats()
const { csrf, headerName } = useCsrf()
const { user } = useUserSession()
const input = ref('')
const currentWeightMode = ref<'deeper' | 'auto' | 'wider'>('auto')
const loading = ref(false)
const router = useRouter()
const route = useRoute()
const { launchResearch, launchingResearch, researchLaunchError } = useResearchLaunch()


const greeting = computed(() => {
  const hour = new Date().getHours()
  let timeGreeting = 'Good evening'
  if (hour < 12) timeGreeting = 'Good morning'
  else if (hour < 18) timeGreeting = 'Good afternoon'

  const name = user.value?.name?.split(' ')[0] || user.value?.username

  return name ? `${timeGreeting}, ${name}` : timeGreeting
})

async function createChat(prompt: string) {
  if (loading.value || !prompt.trim()) return
  input.value = ''
  loading.value = true
  try {
    const chat = await $fetch('/api/chats', {
      method: 'POST',
      headers: { [headerName]: csrf() },
      body: { input: prompt }
    })
    await fetchChats()
    if (chat?.id) {
      router.push(`/chat/${chat.id}`)
    }
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : 'Failed to create chat'
    console.error('createChat error:', msg)
  } finally {
    loading.value = false
  }
}

async function onSubmit() {
  const text = input.value
  if (deepResearchMode.value && text.trim()) {
    const launched = await launchResearch(text, selectedResearchDocumentIds.value)
    if (launched) input.value = ''
    return
  }
  input.value = ''
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

const fileInputRef = ref<HTMLInputElement | null>(null)
const deepResearchMode = ref(route.query.mode === 'research')
const selectedResearchDocumentIds = ref<string[]>([])

function triggerFileUpload() {
  fileInputRef.value?.click()
}

function handleFileUpload(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = (e) => {
    const content = e.target?.result as string
    input.value = (input.value ? input.value + '\n\n' : '') + `[Attached: ${file.name}]\n${content.slice(0, 500)}`
  }
  reader.readAsText(file)
}

const plusMenuItems = computed(() => [[
  {
    label: 'Upload File',
    icon: 'i-lucide-paperclip',
    onSelect: () => triggerFileUpload()
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
          :status="loading || launchingResearch ? 'streaming' : 'ready'"
          class="[view-transition-name:chat-prompt] rounded-2xl shadow-md"
          variant="subtle"
          :ui="{ base: 'px-1.5' }"
          :placeholder="deepResearchMode ? '输入研究问题，并添加本地知识库文件…' : 'Ask me anything...'"
          @submit="onSubmit"
        >
          <template #footer>
            <!-- + Menu: Upload File / Deep Research -->
            <UDropdownMenu :items="plusMenuItems" :content="{ align: 'start' }">
              <UButton
                color="neutral"
                variant="ghost"
                size="sm"
                icon="i-lucide-plus"
                :class="['rounded-full cursor-pointer transition-transform', deepResearchMode ? 'text-emerald-400 rotate-45' : 'text-zinc-400 hover:text-zinc-100']"
              />
            </UDropdownMenu>

            <UButton
              :color="deepResearchMode ? 'primary' : 'neutral'"
              :variant="deepResearchMode ? 'soft' : 'ghost'"
              size="sm"
              icon="i-lucide-telescope"
              :label="deepResearchMode ? '深度研究' : '研究'"
              class="rounded-lg"
              @click="deepResearchMode = !deepResearchMode"
            />

            <!-- Right: WeightMode + Submit -->
            <div class="ms-auto flex items-center gap-1">
              <WeightModeSelect v-model="currentWeightMode" />
              <UChatPromptSubmit color="neutral" size="sm" class="cursor-pointer" />
            </div>
          </template>
        </UChatPrompt>

        <ResearchModeNotice
          v-if="deepResearchMode"
          v-model="selectedResearchDocumentIds"
        />
        <p v-if="researchLaunchError" class="text-sm text-error" role="alert">
          {{ researchLaunchError }}
        </p>

        <!-- Hidden file input -->
        <input ref="fileInputRef" type="file" accept=".txt,.md,.pdf,.docx,.json" class="hidden" @change="handleFileUpload" />


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
