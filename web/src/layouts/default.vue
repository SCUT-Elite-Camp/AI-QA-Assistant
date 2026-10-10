<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { $fetch } from 'ofetch'
import type { DropdownMenuItem } from '@nuxt/ui'
import { defineShortcuts, useToast } from '@nuxt/ui/composables'
import { useChats } from '../composables/useChats'
import { useUserSession } from '../composables/useUserSession'
import { useChatActions } from '../composables/useChatActions'
import { useCsrf } from '../composables/useCsrf'
import ModalSelectTopic from '../components/ModalSelectTopic.vue'
import ModalDashboard from '../components/ModalDashboard.vue'
import ModalSettings from '../components/ModalSettings.vue'

const router = useRouter()
const route = useRoute()
const { loggedIn, fetchSession } = useUserSession()

const showDashboardModal = ref(false)
const showSettingsModal = ref(false)

function openDashboard() {
  window.open('/dashboard', '_blank')
}
const { chats, groups, fetchChats } = useChats()
const { renameChat, deleteChat, createTopicForChat, addChatToTopic } = useChatActions()
const { csrf, headerName } = useCsrf()

fetchSession().catch(() => {})
fetchChats().catch(() => {})

const topics = ref<any[]>([])
async function loadTopics() {
  try {
    topics.value = await $fetch('/api/topics')
  } catch {
    topics.value = []
  }
}
loadTopics().catch(() => {})

const sidebarOpen = ref(false)
const searchOpen = ref(false)
// Track which topics are expanded in the sidebar
const expandedTopics = ref<Set<string>>(new Set())

// Drag and drop state
const draggedChatId = ref<string | null>(null)
const dragOverTopicId = ref<string | null>(null)

// Topic selection modal state
const showSelectTopicModal = ref(false)
const targetChatIdForTopicModal = ref<string | null>(null)

watch(loggedIn, () => {
  fetchChats()
  loadTopics()
  sidebarOpen.value = false
})

// Auto-expand topic if current route chat belongs to that topic
watch(() => [route.path, chats.value], () => {
  const currentChatId = (route.params as { id?: string }).id
  if (currentChatId && chats.value.length) {
    const chat = chats.value.find(c => c.id === currentChatId)
    if (chat && (chat as any).topicId) {
      expandedTopics.value.add((chat as any).topicId)
      expandedTopics.value = new Set(expandedTopics.value)
    }
  }
}, { immediate: true, deep: true })

function toggleTopic(topicId: string) {
  if (expandedTopics.value.has(topicId)) {
    expandedTopics.value.delete(topicId)
  } else {
    expandedTopics.value.add(topicId)
  }
  // Force reactivity
  expandedTopics.value = new Set(expandedTopics.value)
}

// Get all chats belonging to a topic (filtered from already-loaded chats)
function getTopicChats(topicId: string) {
  return chats.value.filter(c => (c as any).topicId === topicId)
}

// Non-topic chats (standalone)
const standaloneChats = computed(() =>
  chats.value.filter(c => !(c as any).topicId)
)

async function createChatInTopic(topicId: string) {
  try {
    const newChat: any = await $fetch(`/api/topics/${topicId}/chats`, {
      method: 'POST',
      headers: { [headerName]: csrf() }
    })
    await fetchChats()
    // Make sure topic is expanded
    expandedTopics.value = new Set([...expandedTopics.value, topicId])
    router.push(`/chat/${newChat.id}`)
  } catch (err: any) {
    useToast().add({ title: '创建对话失败', description: err.message, color: 'error' })
  }
}

// Drag & Drop event handlers
function handleDragStart(chatId: string, event: DragEvent) {
  draggedChatId.value = chatId
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', chatId)
  }
}

function handleDragOver(topicId: string, event: DragEvent) {
  event.preventDefault()
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = 'move'
  }
  dragOverTopicId.value = topicId
}

function handleDragLeave(topicId: string, event: DragEvent) {
  void event
  if (dragOverTopicId.value === topicId) {
    dragOverTopicId.value = null
  }
}

async function handleDropOnTopic(topicId: string, event: DragEvent) {
  event.preventDefault()
  const chatId = draggedChatId.value || event.dataTransfer?.getData('text/plain')
  dragOverTopicId.value = null
  draggedChatId.value = null

  if (chatId && topicId) {
    await addChatToTopic(chatId, topicId)
    await fetchChats()
    expandedTopics.value = new Set([...expandedTopics.value, topicId])
  }
}

const dragOverStandalone = ref(false)

function handleDragOverStandalone(event: DragEvent) {
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  dragOverStandalone.value = true
}

function handleDragLeaveStandalone(event: DragEvent) {
  void event
  dragOverStandalone.value = false
}

async function handleDropOnStandalone(event: DragEvent) {
  event.preventDefault()
  const chatId = draggedChatId.value || event.dataTransfer?.getData('text/plain')
  dragOverStandalone.value = false
  draggedChatId.value = null

  if (chatId) {
    await addChatToTopic(chatId, null)
    await fetchChats()
  }
}

// Modal for "Add to Topic"
function openSelectTopicModal(chatId: string) {
  targetChatIdForTopicModal.value = chatId
  showSelectTopicModal.value = true
}

async function handleSelectTopicForChat(topicId: string) {
  if (targetChatIdForTopicModal.value && topicId) {
    await addChatToTopic(targetChatIdForTopicModal.value, topicId)
    await fetchChats()
    expandedTopics.value = new Set([...expandedTopics.value, topicId])
    targetChatIdForTopicModal.value = null
  }
}

function getChatActions(item: { id: string, label: string, topicId?: string | null }): DropdownMenuItem[][] {
  const isTopicChat = !!item.topicId
  const topicMenuItem = isTopicChat
    ? {
        label: '移出话题',
        icon: 'i-heroicons-folder-minus',
        onSelect: async () => {
          await addChatToTopic(item.id, null)
          await fetchChats()
        }
      }
    : {
        label: '加入话题',
        icon: 'i-heroicons-folder-plus',
        onSelect: () => openSelectTopicModal(item.id)
      }

  return [[
    topicMenuItem,
    {
      label: '新建话题',
      icon: 'i-heroicons-sparkles',
      onSelect: async () => {
        const topic = await createTopicForChat(item.id)
        if (topic?.id) {
          await loadTopics()
          await fetchChats()
          expandedTopics.value = new Set([...expandedTopics.value, topic.id])
        }
      }
    },
    {
      label: '重命名',
      icon: 'i-lucide-pencil',
      onSelect: () => renameChat(item.id, item.label === 'Untitled' ? '' : item.label)
    }
  ], [
    {
      label: '删除',
      icon: 'i-lucide-trash',
      color: 'error' as const,
      onSelect: () => deleteChat(item.id)
    }
  ]]
}

// Items for search and nav (all chats flat)
const searchGroups = computed(() => groups.value)

defineShortcuts({
  meta_o: () => {
    router.push('/')
  }
})
</script>

<template>
  <UDashboardGroup unit="rem">
    <UDashboardSidebar
      id="default"
      v-model:open="sidebarOpen"
      :min-size="12"
      collapsible
      resizable
      class="app-sidebar border-e border-default/70 py-3"
    >
      <template #header="{ collapsed }">
        <ULink
          v-if="!collapsed"
          to="/"
          class="flex items-center gap-2 min-w-0"
        >
          <span class="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <path d="M6 7.5h12M6 12h8M6 16.5h10" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
            </svg>
          </span>
          <span class="text-[15px] font-medium tracking-tight text-highlighted">问答</span>
        </ULink>

        <UDashboardSidebarCollapse class="ms-auto" />
      </template>

      <template #default="{ collapsed }">
        <UNavigationMenu
          :items="[{
            label: '新对话',
            to: '/',
            kbds: ['meta', 'o'],
            icon: 'i-lucide-circle-plus'
          }, {
            label: '搜索',
            icon: 'i-lucide-search',
            kbds: ['meta', 'k'],
            onSelect: () => { searchOpen = true }
          }, {
            label: '话题',
            to: '/topics',
            icon: 'i-heroicons-squares-2x2'
          }, {
            label: '收藏',
            to: '/favorites',
            icon: 'i-lucide-star'
          }]"
          :collapsed="collapsed"
          orientation="vertical"
        >
          <template #item-trailing="{ item }">
            <div
              v-if="item.kbds?.length"
              class="flex items-center gap-px opacity-0 group-hover:opacity-100 transition-opacity"
            >
              <UKbd
                v-for="kbd in item.kbds"
                :key="kbd"
                :value="kbd"
                size="sm"
                variant="soft"
                class="bg-accented/50"
              />
            </div>
          </template>
        </UNavigationMenu>

        <!-- Sidebar chat list (custom, not UNavigationMenu) -->
        <div v-if="!collapsed" class="flex-1 overflow-y-auto min-h-0 mt-1 px-2 space-y-0.5 text-sm">

          <!-- Topic Groups (collapsible & drop targets) -->
          <template v-if="topics.length">
            <p class="text-[11px] font-medium text-muted tracking-wide px-1.5 pt-3 pb-1">话题</p>
            <div v-for="topic in topics" :key="topic.id" class="space-y-0.5">
              <!-- Topic header row (Drop target for dragging chats) -->
              <div
                class="group flex items-center gap-1 rounded-lg px-1.5 py-1.5 hover:bg-accented/50 cursor-pointer transition-all"
                :class="{ 'ring-2 ring-emerald-500 bg-emerald-500/10': dragOverTopicId === topic.id }"
                @click="toggleTopic(topic.id)"
                @dragover.prevent="handleDragOver(topic.id, $event)"
                @dragleave="handleDragLeave(topic.id, $event)"
                @drop.prevent="handleDropOnTopic(topic.id, $event)"
              >
                <!-- Expand/collapse chevron -->
                <UIcon
                  :name="expandedTopics.has(topic.id) ? 'i-lucide-chevron-down' : 'i-lucide-chevron-right'"
                  class="w-3.5 h-3.5 text-muted shrink-0 transition-transform"
                />
                <span class="flex-1 truncate font-medium text-highlighted text-xs">
                  {{ topic.title || '未命名话题' }}
                </span>

                <!-- "+" button: add chat to this topic -->
                <UButton
                  icon="i-lucide-plus"
                  color="neutral"
                  variant="ghost"
                  size="xs"
                  class="opacity-0 group-hover:opacity-100 transition-opacity shrink-0 rounded"
                  aria-label="在此话题下新建对话"
                  @click.stop="createChatInTopic(topic.id)"
                />
              </div>

              <!-- Topic child chats (shown when expanded, Draggable) -->
              <template v-if="expandedTopics.has(topic.id)">
                <div
                  v-for="chat in getTopicChats(topic.id)"
                  :key="chat.id"
                  draggable="true"
                  class="group relative flex items-center ml-5 rounded-lg px-2 py-1.5 hover:bg-accented/50 cursor-pointer transition-colors select-none active:opacity-60"
                  :class="{ 'bg-accented': route.path === `/chat/${chat.id}` }"
                  @click="router.push(`/chat/${chat.id}`)"
                  @dragstart="handleDragStart(chat.id, $event)"
                >
                  <UIcon name="i-lucide-message-circle" class="w-3 h-3 text-muted shrink-0 mr-1.5" />
                  <span class="flex-1 truncate text-xs" :class="chat.label === 'Untitled' ? 'text-muted' : ''">
                    {{ chat.label || 'Untitled' }}
                  </span>
                  <!-- Chat actions "..." -->
                  <div class="absolute right-1 opacity-0 group-hover:opacity-100 transition-opacity" @click.stop>
                    <UDropdownMenu :items="getChatActions({ id: chat.id, label: chat.label, topicId: (chat as any).topicId })" :content="{ align: 'end' }">
                      <UButton
                        as="div"
                        icon="i-lucide-ellipsis"
                        color="neutral"
                        variant="ghost"
                        size="xs"
                        class="rounded"
                        aria-label="Chat actions"
                      />
                    </UDropdownMenu>
                  </div>
                </div>
                <!-- Empty state for topic -->
                <p v-if="!getTopicChats(topic.id).length" class="ml-5 text-[11px] text-muted px-2 py-1">
                  还没有对话
                </p>
              </template>
            </div>
          </template>

          <!-- Standalone Chats (no topic, Draggable & Drop target to remove from topic) -->
          <template v-if="standaloneChats.length">
            <p
              class="text-[11px] font-medium text-muted tracking-wide px-1.5 pt-3 pb-1 rounded-lg transition-all"
              :class="{ 'ring-2 ring-emerald-500 bg-emerald-500/10 text-emerald-400': dragOverStandalone }"
              @dragover.prevent="handleDragOverStandalone($event)"
              @dragleave="handleDragLeaveStandalone($event)"
              @drop.prevent="handleDropOnStandalone($event)"
            >
              对话
            </p>
            <div
              v-for="chat in standaloneChats"
              :key="chat.id"
              draggable="true"
              class="group relative flex items-center rounded-lg px-1.5 py-1.5 hover:bg-accented/50 cursor-pointer transition-colors select-none active:opacity-60"
              :class="{ 'bg-accented': route.path === `/chat/${chat.id}` }"
              @click="router.push(`/chat/${chat.id}`)"
              @dragstart="handleDragStart(chat.id, $event)"
            >
              <span class="flex-1 truncate" :class="chat.label === 'Untitled' ? 'text-muted' : ''">
                {{ chat.label?.replace(/^🌱\s*/, '') || 'Untitled' }}
              </span>
              <!-- Chat actions "..." -->
              <div class="absolute right-1 opacity-0 group-hover:opacity-100 group-has-data-[state=open]:opacity-100 transition-opacity" @click.stop>
                <UDropdownMenu :items="getChatActions({ id: chat.id, label: chat.label, topicId: (chat as any).topicId })" :content="{ align: 'end' }">
                  <UButton
                    as="div"
                    icon="i-lucide-ellipsis"
                    color="neutral"
                    variant="link"
                    size="sm"
                    class="rounded-[5px] hover:bg-accented/50 focus-visible:bg-accented/50 data-[state=open]:bg-accented/50 cursor-pointer"
                    aria-label="Chat actions"
                    tabindex="-1"
                    @click.stop
                  />
                </UDropdownMenu>
              </div>
            </div>
          </template>

        </div>
      </template>

      <template #footer="{ collapsed }">
        <div class="flex items-center gap-2.5">
          <!-- Dashboard Circle Button -->
          <UButton
            icon="i-lucide-layout-dashboard"
            color="neutral"
            variant="none"
            class="w-10 h-10 rounded-full flex items-center justify-center bg-elevated text-muted hover:text-highlighted hover:bg-accented transition-all cursor-pointer active:scale-95 shrink-0"
            aria-label="Dashboard"
            :ui="{ leadingIcon: 'w-5 h-5' }"
            @click="openDashboard"
          />

          <!-- Settings Circle Button -->
          <UButton
            icon="i-lucide-settings"
            color="neutral"
            variant="none"
            class="w-10 h-10 rounded-full flex items-center justify-center bg-elevated text-muted hover:text-highlighted hover:bg-accented transition-all cursor-pointer active:scale-95 shrink-0"
            aria-label="Settings"
            :ui="{ leadingIcon: 'w-5 h-5' }"
            @click="showSettingsModal = true"
          />
        </div>
      </template>
    </UDashboardSidebar>

    <UDashboardSearch
      v-model:open="searchOpen"
      placeholder="搜索对话…"
      :groups="[{
        id: 'links',
        items: [{
          label: '新对话',
          to: '/',
          icon: 'i-lucide-circle-plus'
        }]
      }, ...searchGroups]"
    />

    <div class="flex-1 flex min-w-0 overflow-hidden bg-default">
      <RouterView :key="route.path" />
    </div>

    <!-- Modal for "Add to Topic" -->
    <ModalSelectTopic
      v-if="showSelectTopicModal"
      v-model:open="showSelectTopicModal"
      :chat-id="targetChatIdForTopicModal || undefined"
      :topics="topics"
      @select-topic="handleSelectTopicForChat"
      @create-new-topic="targetChatIdForTopicModal ? createTopicForChat(targetChatIdForTopicModal) : null"
    />

    <!-- Modal for System Dashboard -->
    <ModalDashboard
      v-if="showDashboardModal"
      v-model:open="showDashboardModal"
    />

    <!-- Modal for System Settings -->
    <ModalSettings
      v-if="showSettingsModal"
      v-model:open="showSettingsModal"
    />
  </UDashboardGroup>
</template>
