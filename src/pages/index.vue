<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { $fetch } from 'ofetch'
import { useChats } from '../composables/useChats'
import { useCsrf } from '../composables/useCsrf'
import { useUserSession } from '../composables/useUserSession'
import Navbar from '../components/Navbar.vue'

const { fetchChats } = useChats()
const { csrf, headerName } = useCsrf()
const { user } = useUserSession()
const input = ref('')
const loading = ref(false)
const router = useRouter()

const greeting = computed(() => {
  const hour = new Date().getHours()
  let timeGreeting = '晚上好'
  if (hour < 12) timeGreeting = '早上好'
  else if (hour < 18) timeGreeting = '下午好'

  const name = user.value?.name?.split(' ')[0] || user.value?.username

  return name ? `${timeGreeting}，${name}` : `${timeGreeting}`
})

async function createChat(prompt: string) {
  input.value = prompt
  loading.value = true
  const chat = await $fetch('/api/chats', {
    method: 'POST',
    headers: { [headerName]: csrf() },
    body: { input: prompt }
  })

  await fetchChats()
  router.push(`/chat/${chat?.id}`)
}

function onSubmit() {
  createChat(input.value)
}

const quickChats = [
  { label: '介绍一下你自己', icon: 'i-lucide-bot' },
  { label: '今天天气怎么样？', icon: 'i-lucide-sun' },
  { label: '帮我分析一下销售数据', icon: 'i-lucide-line-chart' },
  { label: '什么是向量数据库？', icon: 'i-lucide-database' },
  { label: '写一个 Vue 3 组件示例', icon: 'i-logos-vue' },
  { label: '如何优化 RAG 检索效果？', icon: 'i-lucide-search' },
  { label: '解释一下 Transformer 架构', icon: 'i-lucide-brain' },
]
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
          class="[view-transition-name:chat-prompt]"
          variant="subtle"
          :ui="{ base: 'px-1.5' }"
          placeholder="输入您的问题..."
          @submit="onSubmit"
        >
          <template #footer>
            <ModelSelect />
            <UChatPromptSubmit color="neutral" size="sm" />
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
