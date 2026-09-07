<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { $fetch } from 'ofetch'
import { useChats } from '../composables/useChats'
import { useCsrf } from '../composables/useCsrf'
import { useUserSession } from '../composables/useUserSession'
import Navbar from '../components/Navbar.vue'
import WeightModeSelect from '../components/chat/WeightModeSelect.vue'

const { fetchChats } = useChats()
const { csrf, headerName } = useCsrf()
const { user } = useUserSession()
const input = ref('')
const currentWeightMode = ref<'deeper' | 'auto' | 'wider'>('auto')
const loading = ref(false)
const router = useRouter()


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

function onSubmit() {
  const text = input.value
  input.value = ''
  if (deepResearchMode.value && text.trim()) {
    router.push({ path: '/research/new', query: { q: text.trim() } })
    return
  }
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
const deepResearchMode = ref(false)

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

            <span v-if="deepResearchMode" class="text-xs font-semibold text-emerald-400 bg-emerald-400/10 px-2 py-0.5 rounded-full">Deep Research</span>

            <!-- Right: WeightMode + Submit -->
            <div class="ms-auto flex items-center gap-1">
              <WeightModeSelect v-model="currentWeightMode" />
              <UChatPromptSubmit color="neutral" size="sm" class="cursor-pointer" />
            </div>
          </template>
        </UChatPrompt>

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
